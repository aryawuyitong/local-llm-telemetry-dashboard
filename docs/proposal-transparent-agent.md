# Proposal: a transparent setup agent for beginners and experienced users

**Status: a prototype for the team to discuss, on the branch `proposal/transparent-agent`.** It isn't merged, and the client hasn't reviewed it. Review it as a team.

## The idea
Local AI Lab should not be a black-box one-click installer, and it shouldn't lose beginners in a terminal either. So the same tool serves two kinds of user, and every step stays visible.

| | Beginner | Experienced |
|---|---|---|
| Pace | One step at a time | The whole plan on one screen |
| Explanation | What it is, why you need it, what changes, how to undo it | One line each, with details one click away |
| Choices | A suggested model and a short reason | Choose any model that fits, and the context size for Try it |
| Going ahead | Approve each step, or type it yourself | Review the commands, then run the remaining steps together |

**The same for everyone:** a compatibility check before any download, the real command on every step, a log of what changed, and the assistant.

## The website, the helper and the latest `main`
This version combines three things: Yitong's Oct 31 `main`, the live website, and the two-level prototype. The website stays the front door and still never touches the laptop.

| Website area | Now | This prototype |
|---|---|---|
| Home | A slogan, then four tabs | Start: pick your memory, get an answer and a Download button, then see the six steps |
| Models | Inside the helper only | A Models page with descriptions, what each needs, and what fits your memory |
| Levels | One path | Commands for experienced users, and the full 7 steps under "Do it all by hand" |
| Results | Charts and import | Unchanged, in the same design |
| When stuck | No help before the helper runs | Paste-your-error box that runs in the browser |
| Trust | Scattered warnings | "What this download does": what it adds, what it never does, how to remove it |
| Learn | Six ideas | Adds local vs. cloud, how a reply is generated, and a "what runs where" map |
| Design | Original colours | Same colours, with larger serif type, self-hosted fonts and light scroll motion adapted from Operation Metier, and Hairline line figures (MIT) that react to the pointer and load only when near the screen |

**The helper is now part of the website.** There's one site. On GitHub it only teaches and offers the download, because a public page can't touch a laptop. The launcher starts the helper, which serves the same `portal/` files from `127.0.0.1` with its launch token, and `portal/lab.js` switches on Set up, real verdicts on Models, measuring, charts that load by themselves, **My lab**, and the assistant. Because the page and helper share one origin, the public site still never calls localhost, and the helper's host, origin and token checks are unchanged.

**My lab** shows models on the laptop, your measurements, and a log of what the agent did. The log stores tool names, never what you typed. **Show on my laptop** opens a model's real file in Finder or File Explorer and shows its path. The path comes from Ollama, and it's checked before anything opens. My lab also names Ollama's models folder itself, with an **Open folder** button, and lists any model Ollama still shows but whose file is gone. The status pill, the Download step and the verify step all check that a model's file is really on disk instead of trusting Ollama's list. The launcher checks for Python 3.11+ and, when there is none, shows what it would download (a checksum-verified CPython build, into the lab folder) and waits for the learner's OK.

**Apps** is the registry's second provider: Visual Studio Code and Obsidian, installed through Homebrew or winget with the same cards, exact commands, log and undo as a model. It exists to prove the registry is general, and it is the first step toward "install anything safely". **Your receipt** in My lab exports one page of what was added, where, how big, and how to undo it. `evaluation/pilot-kit/` lets a teammate run a pilot alone.

**Use it** is a real conversation with any model on the laptop, and **Compare** puts two side by side. **Every card states its time, space, internet, password, money and undo**, and a card without all six can't be built. **Recipes** are reviewed lists of registered steps. **The health check** only reads and offers repair cards, and **the help report** is one page a student reads before choosing to share it.

**The public Demo page** lets a visitor click through the lab with nothing installed. Its cards come from the registry and its replies were recorded from real runs on one Mac, wrong answers included.

**The site was restructured on Nov 10.** Each version has its own short menu and a strip that says which version it is. Models and Apps became one **Catalog** shared by both versions, the lab's measuring pages became one **Measure** page, and the public Results page shows what real laptops measured. The tables above use the earlier page names.

`portal/lab-data.js` is generated from `agent/skill` by `scripts/sync_portal_data.py`, because GitHub Pages only publishes `portal/`. `scripts/check_project.py` fails if it goes out of date.

**The Download button points at the ZIP of `main`**, the same branch GitHub Pages publishes, so it works once this is merged. Change `DOWNLOAD_URL` in `portal/guide.js` when there's a release.

## Why it differs from `main`
| Area | `main` | This prototype |
|---|---|---|
| Who runs setup steps | The learner, in a terminal | The learner approves and the tool runs it, or the learner types it and the tool checks |
| Compatibility | Recommends one model | A verdict for every approved model: ready, close some apps, or won't fit |
| Changes on the laptop | Not tracked | A log, with undo for models the tool downloaded |
| Low free memory | Stops, and the assistant stops too | Plans around half of total memory, and warns. The assistant falls back to labelled rule-based answers |
| Tool choice by the AI | Free tool calling | The model chooses from a fixed list when no router rule applies |
| What the AI may do | Run any tool, including a benchmark, mid-chat | Nothing runs from chat. Tools that would load or measure a model only *propose* a step; the page shows it as the same approval card the plan uses |
| Where a step is defined | Five unlinked places (schema, plan text, executor, log, the AI's toolbox) | One `Action` in `actions.py`: what, why, what changes, undo, command, arguments, executor, log line. Plan, executor, log and guardrail read it |
| Unsafe or invented commands | Block-list | Block-list plus an exact list: a command passes only if it is, byte for byte, one the registry teaches (plain prose commands are checked too) |
| Starting it | Build `.venv` by hand first | The launcher builds it on the first run |

**Unchanged:**
- The helper listens on `127.0.0.1` only and checks the host, origin and token.
- The page can only start fixed actions with allow-listed models.
- Nothing runs a command written by the model or the browser.
- Installing Ollama stays manual, using the official page.
- The command-line tool keeps the stricter memory rule, and the portal and benchmark are unchanged.

## Try it (about 5 minutes)
Open Ollama first. On a Mac, this starts the helper, which opens the website from your laptop:

```sh
scripts/demo.sh
```

1. **Set up → Run this check.** Show the compatibility verdicts.
2. **Beginner:** pick a goal, continue, and open a step. Point out what it is, why, what changes and how to undo it, then **I'll type it myself**.
3. **Switch to Experienced at the top.** The same setup is now one screen.
4. **Choose `qwen2.5:0.5b`** (about 0.4 GB) if you don't have it, then **Run remaining steps**.
5. **Scroll to What changed on your laptop**, then **Undo**, and confirm.
6. **Ask the assistant:** `hey so i finished the download thing, am i good to go`. The chip shows the AI picked the tool.

Finish with **Models** (set up any model from its card), **Results** and **My lab**. To see the public version, run `npm run preview` and try the memory buttons and the error box with `zsh: command not found: ollama`.

## Decisions for the team
1. **Does approve-to-run fit "manual deployment stays the learning path"?** The scope says manual. This needs the client's agreement, so raise it with them.
2. **Is half of total memory a safe planning rule?** It was chosen because free memory on Macs swings a lot. Test it on smaller laptops and on Windows.
3. **Who reviews this with Yitong?** It changes code Yitong reworked on Oct 31.
4. **How do we handle unsigned downloads?** The website tells people not to change security settings and points them to the commands if they're blocked. Signing would remove that friction, and costs about $99 a year on Mac.

## Known limits
- **Tested on one Apple M5 Mac only.** Windows, including the `.bat` launcher and starting Ollama, is untested.
- **The model still writes the open answers, and they can be wrong.** Code now answers facts about the laptop, and a reply says who wrote it. On 24 untuned questions with qwen2.5:3b, 11 of 16 about the lab got the right answer, 3 went to the model, and 2 got a true answer to the wrong question. All 8 general questions went to the model. We wrote those questions ourselves, so this isn't an independent test. qwen2.5:0.5b and 1.5b each chose correctly only 6 times in 24, so only models of 3B or more choose. With a smaller model, wordings the patterns miss go to the model.
- **The tool choice result needs a fresh test.** The 10 of 10 result came from a small set I wrote, and argument handling wasn't part of it.
- **Multi-step plans come from reviewed recipes, not from chat.** The assistant still proposes one step at a time. No shipped recipe has been run to its final check on a real laptop yet, so their review fields are empty. The page only shows a review once one is filled in.
- **The command check is now exact** (registered commands only, in code or prose), so invented commands such as `python -m ollama benchmark` are rejected. Prose such as "turn Defender off for a few minutes" is still a separate rule, and the 43-case audit hasn't been re-run since.
- **Experienced options are limited.** Model and context size only. Threads, quantization and install folder aren't built.
- **The website picker has one real measurement so far.** Everything else on it is a planning estimate, and it's labelled that way.
- **The quiz was rewritten on Nov 5** to ten scenario questions on what the site teaches, with explanations held back until the post-test. It still needs a pilot to show it measures anything.
- **The private Python download is untested.** The launcher offers it on a laptop without Python 3.11+, but it hasn't yet run on one, on Mac or Windows.
- **The evaluation suites were last re-run on Nov 6, with the current playbook.** They gave 20/20 and 0/15 unsafe on our own development cases, which is not an independent study. They test the agent alone, not the answers code writes.
- **A real app install and Undo haven't run yet.** Both test apps were already on the only laptop tried.
- **The Mac Ollama install is untested on a clean laptop.** If it asks for a password to add its command-line tool, the card says to skip that part. Confirm this in the first pilot.
