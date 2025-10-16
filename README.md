# skipera
<img width="96" height="96" alt="image" src="https://github.com/user-attachments/assets/8cf9428c-ef58-45b2-8fff-184ae353a890" />

Module to facilitate skipping Coursera (https://www.coursera.org/) videos and assessments.

If you want to use Perplexity instead of Gemini, check out the original [repo](https://github.com/serv0id/skipera)

## Why?
Skipera assists in automatically skip irrelevant MOOC courses which are made mandatory by universities. 
Many of such courses are allotted directly by the university as credit fillers and are not in the interest of the student. The progress of the completion of these courses is tracked by the university and credits are allotted.

## How?
Skipera makes use of the Coursera web API and completes the videos + reading materials.
Graded assessments are completed with the assistance of an LLM API.

## LLM Support
If you wish to solve graded assignments automatically, you can add your Gemini API Key to the config and define a 
relevant model.

Currently, only the single-choice and multiple-choice objective questions are supported in this mode. Note that you might
not always achieve passing marks due to the LLM hallucinating sometimes.

## How to use
* A sample config is provided in the repo. For now, cookie auth has been implemented since login requires reCaptcha.
* Add your cookies to the config as key-value pairs (simple python dict). The presence of the "CAUTH" cookie is important. (https://github.com/serv0id/skipera/issues/1)
* Add your Gemini API Key if you wish to use the LLM to solve graded assignments. Use the `--llm` flag if you wish to solve graded assignments automatically.
* `python3 main.py --slug course-slug` where course-slug is present in the Coursera Course URL. Example: "introduction-psychology" (without the quotes) if the URL is https://www.coursera.org/learn/introduction-psychology/home/module/2
* for Windows users just run gui.bat
