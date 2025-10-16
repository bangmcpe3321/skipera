# https://github.com/serv0id/skipera
import click
import requests
import config
from loguru import logger
from assessment.solver import GradedSolver


class Skipera(object):
    def __init__(self, course: str, llm: bool):
        self.user_id = None
        self.course_id = None
        self.base_url = config.BASE_URL
        self.session = requests.Session()
        self.session.headers.update(config.HEADERS)
        self.session.cookies.update(config.COOKIES)
        self.course = course
        self.llm = llm
        if not self.get_userid():
            # The program will exit if authentication fails.
            exit(1)

    def login(self):
        logger.debug("Trying to log in using credentials")
        r = self.session.post(self.base_url + "login/v3", json={
            "code": "",
            "email": config.EMAIL,
            "password": config.PASSWORD,
            "webrequest": True,
        })

        logger.info(r.content)

    def get_userid(self):
        r = self.session.get(self.base_url + "adminUserPermissions.v1?q=my").json()
        try:
            self.user_id = r["elements"][0]["id"]
            logger.info("User ID: " + self.user_id)
        except (KeyError, IndexError):
            # FIX: Provide a more specific and actionable error message if the initial
            # authentication check fails, as this is a common point of failure.
            if r.get("errorCode"):
                logger.error(f"Authentication Error: {r['errorCode']}. Your COOKIES are likely expired or invalid. Please update them in config.py and try again.")
            else:
                logger.error("Could not retrieve User ID. Your COOKIES are likely expired or invalid. Please update them in config.py and try again.")
            return False
        return True

    # hierarchy - Modules > Lessons > Items
    def get_modules(self):
        r = self.session.get(self.base_url
                             + f"onDemandCourseMaterials.v2/?q=slug&slug={self.course}&includes=modules").json()
        self.course_id = r["elements"][0]["id"]
        logger.debug("Course ID: " + self.course_id)
        logger.debug("Number of Modules: " + str(len(r["linked"]["onDemandCourseMaterialModules.v1"])))
        for x in r["linked"]["onDemandCourseMaterialModules.v1"]:
            logger.info(x["name"] + " -- " + x["id"])

    def get_items(self):
        r = self.session.get(self.base_url + "onDemandCourseMaterials.v2/", params={
            "q": "slug",
            "slug": self.course,
            "includes": "passableItemGroups,passableItemGroupChoices,items,tracks,gradePolicy,gradingParameters",
            "fields": "onDemandCourseMaterialItems.v2(name,slug,timeCommitment,trackId)",
            "showLockedItems": "true"
        }).json()
        for video in r["linked"]["onDemandCourseMaterialItems.v2"]:
            logger.info("Processing " + video["name"])
            self.watch_item(video["id"])

    def watch_item(self, item_id):
        r = self.session.post(
            self.base_url + f"opencourse.v1/user/{self.user_id}/course/{self.course}/item/{item_id}/lecture"
                            f"/videoEvents/ended?autoEnroll=false",
            json={"contentRequestBody": {}}).json()
        if r.get("contentResponseBody") is None:
            logger.info("Not a watch item! Attempting to read or solve...")
            self.read_item(item_id)

    def read_item(self, item_id):
        r = self.session.post(self.base_url + "onDemandSupplementCompletions.v1", json={
            "courseId": self.course_id,
            "itemId": item_id,
            "userId": int(self.user_id)
        })
        if "Completed" not in r.text:
            logger.debug("Item is not a reading supplement, assuming it is a quiz/assignment.")
            if self.llm:
                logger.info(f"Attempting to solve graded assessment: {item_id}")
                solver = GradedSolver(self.session, self.course_id, item_id)
                solver.solve()
            else:
                logger.warning(f"Item {item_id} is a quiz/assignment, but the --llm flag is not set. Skipping.")


import tkinter as tk
from tkinter import simpledialog

def prompt_for_api_key():
    """
    Prompts the user for the Gemini API key and saves it to the config file.
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    api_key = simpledialog.askstring("API Key", "Please enter your Gemini API key:", show='*')
    if api_key:
        with open("config.py", "r") as f:
            lines = f.readlines()
        with open("config.py", "w") as f:
            for line in lines:
                if line.startswith("GEMINI_API_KEY"):
                    f.write(f'GEMINI_API_KEY = "{api_key}"\n')
                else:
                    f.write(line)
        config.GEMINI_API_KEY = api_key
    return api_key

@logger.catch
@click.command()
@click.option('--slug', required=True, help="The course slug from the URL")
@click.option('--llm', is_flag=True, help="Whether to use an LLM to solve graded assignments.")
def main(slug: str, llm: bool) -> None:
    if llm and not config.GEMINI_API_KEY:
        if not prompt_for_api_key():
            logger.error("LLM functionality requires a Gemini API key.")
            return
    skipera = Skipera(slug, llm)
    skipera.get_modules()
    skipera.get_items()


if __name__ == '__main__':
    main()