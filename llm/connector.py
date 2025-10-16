# https://github.com/serv0id/skipera
import json
import requests
from config import GEMINI_API_KEY
from pydantic import BaseModel
from typing import List, Literal, Optional
from loguru import logger


# FIX: Updated the response format to handle both multiple-choice (option_id) and
# text-based (answer) responses from the LLM. The `type` field now includes 'Text'
# to differentiate between question formats.
class ResponseFormat(BaseModel):
    question_id: str
    option_id: Optional[List[str]] = None
    answer: Optional[str] = None
    type: Literal["Single", "Multi", "Text"]


class ResponseList(BaseModel):
    responses: List[ResponseFormat]


class GeminiConnector(object):
    def __init__(self):
        self.API_URL: str = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        self.API_KEY: str = GEMINI_API_KEY

    def get_response(self, questions: dict) -> dict:
        """
        Sends the questions to Gemini and asks for the answers
        in a JSON format.
        """
        logger.debug("Making an API Request to Gemini..")

        # FIX: The system prompt is now more detailed, instructing the AI on how to handle
        # different question types and return the correct field (`option_id` or `answer`).
        system_prompt = (
            "You are an expert university professor and a subject matter expert in this field. Your task is to solve a graded university-level assignment. Your answers must be precise and accurate, as a failing grade is not an option."
            "\n\n**Instructions for your thought process (do not include this in the final JSON output):**"
            "\n1.  **Analyze the Question:** Read each question carefully to fully understand what is being asked. Identify key concepts, constraints, and requirements."
            "\n2.  **Chain of Thought:** For each question, reason through the problem step-by-step. "
            "    - If it is multiple choice, evaluate each option against the question. Eliminate incorrect options and justify why the chosen option is the best fit."
            "    - If it requires a text or numeric answer, formulate your response based on your expert knowledge and calculations. Double-check your answer for correctness."
            "\n3.  **Final Answer Formulation:** After your internal reasoning process is complete, format your final answer into the required JSON structure."
            "\n\n**Instructions for the final JSON output:**"
            "\n- The user has provided a JSON object where each key is a unique `question_id`."
            "\n- Your response must be a JSON object containing a single key `responses`, which is a list of answer objects."
            "\n- Each answer object must contain:"
            "\n  - `question_id`: The ID of the question you are answering."
            "\n  - `type`: The type of question, which will be 'Single-Choice', 'Multi-Choice', or 'Text-Entry'."
            "\n  - **`option_id` OR `answer`**: "
            "\n    - For 'Single-Choice' or 'Multi-Choice', provide the correct `option_id`(s) in the `option_id` field. The `answer` field must be `null`."
            "\n    - For 'Text-Entry' questions (like numeric, regex, or free-text), provide the calculated or formulated string in the `answer` field. The `option_id` field must be `null`."
            "\n- Do not include any explanations, reasoning, or extra text in the final JSON output. It must strictly adhere to the schema."
        )

        # FIX: The response schema is updated to be more flexible, allowing either 'option_id'
        # or 'answer' to be present in the response for each question.
        response_schema = {
            "type": "object",
            "properties": {
                "responses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_id": {"type": "string"},
                            "option_id": {
                                "type": "array",
                                "items": {"type": "string"},
                                "nullable": True
                            },
                            "answer": {
                                "type": "string",
                                "nullable": True
                            },
                            "type": {
                                "type": "string",
                                "enum": ["Single", "Multi", "Text"]
                            }
                        },
                        "required": ["question_id", "type"]
                    }
                }
            },
            "required": ["responses"]
        }

        response = requests.post(url=self.API_URL, headers={
            "Content-Type": "application/json"
        }, params={
            "key": self.API_KEY
        }, json={
            "contents": [
                {
                    "parts": [
                        {"text": system_prompt},
                        {"text": json.dumps(questions)}
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": response_schema
            }
        }).json()

        if "error" in response:
            logger.error(f"Gemini API Error: {response['error']['message']}")
            return {}

        return json.loads(response["candidates"][0]["content"]["parts"][0]["text"])