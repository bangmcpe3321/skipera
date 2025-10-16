import time
import requests
from bs4 import BeautifulSoup
import json

from assessment.types import QUESTION_TYPE_MAP, MODEL_MAP, deep_blank_model, WHITELISTED_QUESTION_TYPES
from config import GRAPHQL_URL
from assessment.queries import (GET_STATE_QUERY, SAVE_RESPONSES_QUERY, SUBMIT_DRAFT_QUERY,
                                GRADING_STATUS_QUERY, INITIATE_ATTEMPT_QUERY)
from loguru import logger
from llm.connector import GeminiConnector


class GradedSolver(object):
    def __init__(self, session: requests.Session, course_id: str, item_id: str):
        self.session: requests.Session = session
        self.course_id: str = course_id
        self.item_id: str = item_id
        self.attempt_id = None
        self.draft_id = None
        self.question_type_cache = {}

    def solve(self):
        """
        Main entry point for solving an assignment. It checks the assignment state
        and decides whether to start a new attempt or resume an existing one,
        then proceeds with the solving logic based on the assessment type.
        """
        state = self.get_state()

        if state is None:
            logger.warning(
                f"Could not retrieve a valid state for item {self.item_id}. This might be an ungraded quiz, a survey, or an item you don't have permission to access. Skipping.")
            return

        # --- MODIFICATION START: Logic to handle different assessment types ---
        # This is a placeholder for the detection logic. You may need to inspect the
        # 'state' object to find the correct field that differentiates quiz types.
        # Common fields could be 'presentationPolicy', 'layout', or 'submissionType'.
        # For now, we assume 'SEQUENTIAL' as the safe default.
        #
        # Example of a potential real check:
        # assessment_type = state.get("assignment", {}).get("presentationPolicy", "SEQUENTIAL")

        assessment_type = "SEQUENTIAL"  # Defaulting to the robust sequential method.
        # Change this to "SINGLE_PAGE" to test the new logic.

        logger.info(f"Detected assessment type as '{assessment_type}'.")
        # --- MODIFICATION END ---

        if state.get("allowedAction") == "RESUME_DRAFT":
            logger.info("An attempt is already in progress. Resuming...")
            if assessment_type == "SINGLE_PAGE":
                self._solve_single_page(state)
            else:
                self._solve_sequentially(state)

        elif state.get("allowedAction") == "START_NEW_ATTEMPT":
            if state.get("outcome") and state["outcome"].get("isPassed"):
                logger.debug("Already passed!")
                return

            if state.get("attempts", {}).get("attemptsRemaining") == 0:
                logger.error("No more attempts can be made!")
                return

            if not self.initiate_attempt():
                logger.error("Could not start an attempt. Please file an issue.")
                return

            logger.info("New attempt started. Solving...")
            time.sleep(2)

            # Refetch state after starting the attempt
            new_state = self.get_state()
            if new_state is None:
                logger.error("Could not fetch state after starting a new attempt. Aborting.")
                return

            if assessment_type == "SINGLE_PAGE":
                self._solve_single_page(new_state)
            else:
                self._solve_sequentially(new_state)

        else:
            logger.error(f"Unsupported action: {state.get('allowedAction')}. Please file an issue.")

    # --- NEW FUNCTION START: Solver for single-page assessments ---
    def _solve_single_page(self, state: dict):
        """
        Solves all questions on a single-page assessment in one batch.
        """
        if not state or "inProgressAttempt" not in state.get("attempts", {}):
            logger.error("Could not find an active attempt to continue. Aborting.")
            return

        draft = state["attempts"]["inProgressAttempt"]
        self.draft_id = draft["id"]
        self.attempt_id = draft["draft"]["id"]
        questions = draft["draft"]["parts"]

        questions_to_solve_formatted = {}
        other_question_responses = []
        found_unanswered = False

        for question in questions:
            q_type = question["__typename"]
            part_id = question["partId"]

            if q_type not in MODEL_MAP:
                continue

            self.question_type_cache[part_id] = q_type
            response_key, q_type_enum = QUESTION_TYPE_MAP[q_type]
            response_data = question.get(response_key)

            is_answered = response_data and any(
                response_data.get(key) for key in ["chosen", "answer", "plainText", "richText", "fileUrl"])

            if is_answered:
                if response_data:
                    response_data.pop('__typename', None)
                other_question_responses.append({
                    "questionId": part_id, "questionType": q_type_enum,
                    "questionResponse": {response_key: response_data}
                })
            elif q_type in WHITELISTED_QUESTION_TYPES:
                found_unanswered = True
                prompt_html = question["questionSchema"]["prompt"].get("cmlValue", "")
                soup = BeautifulSoup(prompt_html, 'html.parser')
                prompt_text = soup.get_text(separator=' ', strip=True)

                if q_type in ["Submission_CheckboxQuestion", "Submission_MultipleChoiceQuestion"]:
                    options = [{"option_id": opt["optionId"],
                                "value": BeautifulSoup(opt["display"]["cmlValue"], 'html.parser').get_text(
                                    separator=' ', strip=True)} for opt in question["questionSchema"]["options"]]
                    q_format_type = "Single-Choice" if q_type == "Submission_MultipleChoiceQuestion" else "Multi-Choice"
                    questions_to_solve_formatted[part_id] = {"Question": prompt_text, "Options": options,
                                                             "Type": q_format_type}
                else:
                    questions_to_solve_formatted[part_id] = {"Question": prompt_text, "Type": "Text-Entry"}
            else:  # Not whitelisted and not answered
                other_question_responses.append({
                    "questionId": part_id, "questionType": q_type_enum,
                    "questionResponse": {response_key: deep_blank_model(MODEL_MAP[q_type])}
                })

        if not found_unanswered:
            logger.info("All solvable questions appear to be answered. Proceeding to submission.")
            if self.submit_draft():
                self.check_grade()
            else:
                logger.error("Could not submit the assignment. Please file an issue.")
            return

        logger.info(
            f"Found {len(questions_to_solve_formatted)} unanswered questions. Sending to LLM in a single batch.")

        connector = GeminiConnector()
        answers = connector.get_response(questions_to_solve_formatted)

        if not answers or "responses" not in answers or not answers["responses"]:
            logger.error("Could not get a valid response from the LLM. Aborting.")
            return

        if not self.save_responses(answers["responses"], other_question_responses):
            logger.error("Could not save the batch of responses. Aborting.")
            return

        logger.info("All answers saved successfully. Submitting assignment.")

        if self.submit_draft():
            self.check_grade()
        else:
            logger.error("Could not submit the assignment. Please file an issue.")

    # --- NEW FUNCTION END ---

    def _solve_sequentially(self, state: dict):
        """
        Solves questions one by one in a loop, fetching state each time.
        (Original solving method)
        """
        # Pass initial state to avoid re-fetching on the first loop
        initial_state = state

        while True:
            # On subsequent loops, state will be None and we must refetch
            if initial_state is None:
                state = self.get_state()
            else:
                state = initial_state
                initial_state = None  # Clear it after first use

            if not state or "inProgressAttempt" not in state.get("attempts", {}):
                logger.error("Could not find an active attempt to continue. Aborting.")
                return

            draft = state["attempts"]["inProgressAttempt"]
            self.draft_id = draft["id"]
            self.attempt_id = draft["draft"]["id"]

            questions = draft["draft"]["parts"]

            question_to_solve_formatted = None
            found_unanswered_whitelisted_question = False
            other_question_responses = []

            for question in questions:
                q_type = question["__typename"]
                part_id = question["partId"]

                if q_type not in MODEL_MAP:
                    continue

                self.question_type_cache[part_id] = q_type
                response_key, q_type_enum = QUESTION_TYPE_MAP[q_type]
                response_data = question.get(response_key)

                is_answered = response_data and any(
                    response_data.get(key) for key in ["chosen", "answer", "plainText", "richText", "fileUrl"])

                if is_answered:
                    if response_data:
                        response_data.pop('__typename', None)
                    other_question_responses.append({
                        "questionId": part_id,
                        "questionType": q_type_enum,
                        "questionResponse": {response_key: response_data}
                    })
                elif not found_unanswered_whitelisted_question and q_type in WHITELISTED_QUESTION_TYPES:
                    found_unanswered_whitelisted_question = True
                    prompt_html = question["questionSchema"]["prompt"].get("cmlValue", "")
                    soup = BeautifulSoup(prompt_html, 'html.parser')
                    prompt_text = soup.get_text(separator=' ', strip=True)

                    if q_type in ["Submission_CheckboxQuestion", "Submission_MultipleChoiceQuestion"]:
                        options = [{"option_id": opt["optionId"],
                                    "value": BeautifulSoup(opt["display"]["cmlValue"], 'html.parser').get_text(
                                        separator=' ', strip=True)} for opt in question["questionSchema"]["options"]]
                        q_format_type = "Single-Choice" if q_type == "Submission_MultipleChoiceQuestion" else "Multi-Choice"
                        question_to_solve_formatted = {
                            part_id: {"Question": prompt_text, "Options": options, "Type": q_format_type}}
                    else:
                        question_to_solve_formatted = {part_id: {"Question": prompt_text, "Type": "Text-Entry"}}
                else:
                    other_question_responses.append({
                        "questionId": part_id,
                        "questionType": q_type_enum,
                        "questionResponse": {response_key: deep_blank_model(MODEL_MAP[q_type])}
                    })

            if not found_unanswered_whitelisted_question:
                logger.info("All solvable questions appear to be answered. Proceeding to submission.")
                break

            connector = GeminiConnector()
            answers = connector.get_response(question_to_solve_formatted)

            if not answers or "responses" not in answers or not answers["responses"]:
                logger.error("Could not get a valid response from the LLM. Aborting.")
                return

            if not self.save_responses(answers["responses"], other_question_responses):
                logger.error("Could not save the response. Aborting.")
                return

            logger.info(f"Answered and saved question ID: {list(question_to_solve_formatted.keys())[0]}")
            time.sleep(2)

        if self.submit_draft():
            self.check_grade()
        else:
            logger.error("Could not submit the assignment. Please file an issue.")

    def check_grade(self):
        """Polls for the final grade after submission."""
        logger.debug("Waiting for grading results...")
        max_retries = 6
        retry_delay = 5
        for i in range(max_retries):
            outcome = self.get_grade()
            if outcome:
                if outcome.get('isPassed'):
                    logger.info("Successfully passed the assignment.")
                else:
                    logger.error("Sorry! Could not pass the assignment, maybe use a better model.")
                return
            logger.debug(f"Grading not ready, retrying in {retry_delay}s... ({i + 1}/{max_retries})")
            time.sleep(retry_delay)
        else:
            logger.error("Timed out waiting for grading results.")

    def get_state(self) -> dict:
        """
        Retrieves the current state of the assessment, with robust error handling.
        """
        try:
            res = self.session.post(url=GRAPHQL_URL, params={"opname": "QueryState"}, json={
                "operationName": "QueryState",
                "variables": {"courseId": self.course_id, "itemId": self.item_id},
                "query": GET_STATE_QUERY
            }).json()

            query_state = res.get("data", {}).get("SubmissionState", {}).get("queryState")

            if query_state is None:
                logger.warning(f"API response for item {self.item_id} did not contain a valid 'queryState'.")
                logger.debug(f"Full API response: {res}")
                return None

            return query_state

        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            logger.error(f"An error occurred while fetching assignment state for item {self.item_id}: {e}")
            return None

    def initiate_attempt(self) -> bool:
        res = self.session.post(url=GRAPHQL_URL, params={"opname": "Submission_StartAttempt"}, json={
            "operationName": "Submission_StartAttempt",
            "variables": {"courseId": self.course_id, "itemId": self.item_id},
            "query": INITIATE_ATTEMPT_QUERY
        })
        return "Submission_StartAttemptSuccess" in res.text

    def save_responses(self, new_answers: list, existing_responses: list) -> bool:
        """
        Saves a payload containing new answers and all other existing/blank responses.
        """
        answer_payload = []
        for answer in new_answers:
            question_id = answer["question_id"]
            original_type = self.question_type_cache.get(question_id)
            if not original_type:
                continue

            response_key, q_type_enum = QUESTION_TYPE_MAP[original_type]

            response_payload_data = {}
            if answer["type"] in ["Single", "Multi"]:
                chosen = answer.get("option_id")
                if answer["type"] == "Single" and isinstance(chosen, list):
                    chosen = chosen[0] if chosen else None
                response_payload_data = {response_key: {"chosen": chosen}}
            elif answer["type"] == "Text":
                text_answer = answer.get("answer", "")
                if original_type == "Submission_PlainTextQuestion":
                    response_payload_data = {response_key: {"plainText": text_answer}}
                else:
                    response_payload_data = {response_key: {"answer": text_answer}}
            else:
                continue

            answer_payload.append({
                "questionId": question_id,
                "questionType": q_type_enum,
                "questionResponse": response_payload_data
            })

        final_responses = [*answer_payload, *existing_responses]
        if not final_responses:
            logger.debug("No responses to save.")
            return True

        res = self.session.post(url=GRAPHQL_URL, params={"opname": "Submission_SaveResponses"}, json={
            "operationName": "Submission_SaveResponses",
            "variables": {
                "input": {
                    "courseId": self.course_id,
                    "itemId": self.item_id,
                    "attemptId": self.draft_id,
                    "questionResponses": final_responses
                }
            },
            "query": SAVE_RESPONSES_QUERY
        })

        if "Submission_SaveResponsesSuccess" in res.text:
            return True

        logger.error(f"Failed to save responses. Payload: {final_responses}")
        logger.error(f"Server response: {res.json()}")
        return False

    def submit_draft(self) -> bool:
        res = self.session.post(url=GRAPHQL_URL, params={"opname": "Submission_SubmitLatestDraft"}, json={
            "operationName": "Submission_SubmitLatestDraft",
            "query": SUBMIT_DRAFT_QUERY,
            "variables": {
                "input": {"courseId": self.course_id, "itemId": self.item_id, "submissionId": self.attempt_id}
            }
        })
        return "Submission_SubmitLatestDraftSuccess" in res.text

    def get_grade(self) -> dict:
        res = self.session.post(url=GRAPHQL_URL, params={"opname": "QueryState"}, json={
            "operationName": "QueryState",
            "query": GET_STATE_QUERY,
            "variables": {"courseId": self.course_id, "itemId": self.item_id}
        }).json()
        outcome = res.get("data", {}).get("SubmissionState", {}).get("queryState", {}).get("outcome")
        if outcome:
            logger.debug(f"Achieved {outcome.get('earnedGrade')} grade. Passed? {outcome.get('isPassed')}")
        return outcome