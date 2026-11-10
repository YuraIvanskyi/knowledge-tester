Within knowledege-tester directory a new web app should be created that acts as a local version of google forms, to do some basic testing in educational areas. 

The whole system should support easy tests setup, tests project management, tests export (in json) in dedicatedd admin part or inside teacher account.
Each test should be it's own page available to be shared via link & qr code in local network for guests to take it without need for internet access (just network of the test host).

Another Key features - autograding & result printing. 
Tests can have grades enabled per task, with rules to put marks for single-correct, few-correct, multiple-choice, open-question type of tasks to have logic behind.
Final test answers should have print option, where responses are compacted into a lean pdf to pass-on to where requested.
Each "sheet" is a Student/test-taker info + question/answer sequences.

On top of that, a teacher/student profiling system should also exist, where teacher can save results for some students.
As a helping solution, a local llm suport should be integrated to some key areas, where as an assistant it would organize/structure some parts, import users from text/image/file - basic but helpfull stuff.

Localization - to be defined, with English and Ukrainian as starting ones, but implementation goes with english suported first.

UI/UX - simple, practical, mandatory for easy to be viewed on mobile devices, without known AI-like design features (left borders, colors etc.)

Export/Import files for system need to have a simple yet robust schema description so either local llm or cloud llm could easily understand and create a test file to be used in the app.

Create a detailed plan inside that folder, advise best framework/tech (e.g. django) (and all required modules possibly needed) as tech stack. Application is to be relatively lightweight so it does account for low-end devices/networks.

Later on, we will use that plan to implement it incrementally.
Save plan to plan.md file in idea folder.

Idea folder is to be structured for project tracking, issue management, plans etc. Some project board file for overall progress to be kept.