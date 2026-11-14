# Desktop Lab Helper release

The downloadable Lab Helper opens the dashboard in the learner's browser. It
bundles Python, the dashboard and the Lab Helper, so learners can open the app
without downloading a source repository or running a terminal command.
Ollama is a separate installation for native model runs. The dashboard checks
available Ollama models and reuses their existing files.

## Build a candidate

Run **Build the desktop Lab Helper** in GitHub Actions. Leave the tag field
empty for test artifacts. To stage a draft release, create a version tag for
the reviewed commit and rerun the workflow with the tag. The workflow builds
the exact tagged files, tests each bundle with a token-protected loopback
server, and stages a draft after all three jobs pass.

| Target | Learner download | Open after extracting the entire archive |
| --- | --- | --- |
| Apple silicon | `Local-AI-Lab-macos-arm64.zip` | `Local AI Lab.app` |
| Intel Mac | `Local-AI-Lab-macos-x64.zip` | `Local AI Lab.app` |
| Windows x64 | `Local-AI-Lab-windows-x64.zip` | `Local AI Lab/Local AI Lab.exe` |

The Windows executable needs its adjacent `_internal` directory. Each app
opens the browser with a private session link. Its small control window can
reopen the browser or stop the local helper. Results live under
`~/Library/Application Support/Local AI Lab/results` on Mac and
`%LOCALAPPDATA%\Local AI Lab\results` on Windows. The existing Ollama model
store is shared with the runtime.

For a development build, use Python 3.12 with Tk on the target OS and run:

```sh
python -m pip install -r agent/requirements.txt -r scripts/requirements-desktop.txt
python scripts/build_lab_app.py
```

## Validate before publishing

The workflow produces unsigned release candidates. Sign and notarize the
macOS app with the team's Developer ID and sign the Windows executables
using the team's verified Windows signing process. Rearchive the signed
bundles and replace the candidate assets in the draft. Re-run the bundle
smoke test and verify the OS accepts the signed downloads before publishing.

Test a clean standard user account on each supported platform. Verify launch
without Python, Ollama discovery and start, a fresh lightweight model download,
reuse of existing model files, two selected models benchmarked in sequence,
and saved results after a restart. Record package sizes and first-run timings
from the tested machines. CI smoke tests verify packaging and local endpoints.
Physical Mac and Windows inference tests verify learner use on their respective
hardware.
