Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.
2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

"Add validation" → "Write tests for invalid inputs, then make them pass"
"Fix the bug" → "Write a test that reproduces it, then make it pass"
"Refactor X" → "Ensure tests pass before and after"
For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

5. File-Write Encryption on This Machine (HARD RULE)
This machine has TipRay 天锐绿盾 transparent encryption (TsdEncrypt.sys driver, `%TSD-Header-###%` file prefix, on-disk size a multiple of 8192).
Whether a written file comes out encrypted depends on WHICH PROCESS creates it and whether that process has opened a protected file. Verified on this machine 2026-09-17: most writers produce ciphertext for .py/.js/.json/.md/.csv/.html (and sometimes .vue), which breaks git commits, Docker deploys and builds.

The ONLY allowed way to write project files (verified plaintext for .py/.js/.json/.md/.csv/.vue/.html, new files and overwriting existing files):
- Read the source with `git show HEAD:<path>` or python, modify the text in python.
- Let cmd.exe create the target file via its `>` redirect, and feed the bytes through stdin. cmd.exe itself must NOT open any source file:

```python
import subprocess, sys
def write(target, text):
    cmd = 'cmd.exe /d /s /c ""' + sys.executable + '" -c "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())" > "' + str(target) + '""'
    subprocess.run(cmd, input=text.encode("utf-8"), check=True)
```

Run such python from PowerShell as `@' ... '@ | python -`.

FORBIDDEN writers (produce `%TSD-Header-###%` ciphertext):
- Claude Code `Write`, `Edit`, `NotebookEdit` tools.
- `cmd.exe /c "type SRC > DEST"` (this is what encrypted PreRequestCenter.vue / PriceApprovalWorkbench.vue on 2026-09-16), and any cmd command that reads a file and redirects it.
- WSL writes, e.g. `wsl ... sh -c 'cat SRC > DEST'`.
- Bash `>` / heredoc / `sed -i` / `awk` redirects, PowerShell `Set-Content` / `Out-File` / `[IO.File]::WriteAllText`.
- Local `node` / `vite build` / `yarn build` (build and test inside Docker instead).

Verify EVERY write with git, never with python (python may see decrypted bytes):
- `git diff --numstat -- <path>` must show line counts, not `-  -` / `Bin`; or `git hash-object --no-filters <path>` equals the expected hash.
- If a file turns out encrypted: stop and tell the user. Do not commit it and do not deploy it.

Reading: `cmd.exe type` of a protected file may return ciphertext and does NOT decrypt. An already-encrypted file that is unchanged from Git can be restored with `git checkout -- <path>` (only with the user's go-ahead). The real long-term fix is IT: mark `D:\rayher` as a plaintext directory in TipRay, or trust the development processes by name.

6. Development and Deployment Workflow (HARD RULE)
Local Git is the only source of truth. Docker only ever runs a commit that exists in the local repo.

The ONLY workflow:
1. Edit in the local worktree `D:\rayher\rayher-logistics-main` (using the plaintext-safe writer from section 5).
2. `git commit` locally. The pre-commit hook in `.githooks/` refuses TipRay ciphertext and non-UTF-8 text.
   Enable it once per clone: `git config core.hooksPath .githooks`.
3. Deploy with `powershell -File .\scripts\deploy-to-docker.ps1` (try `-DryRun` first).

Never:
- Edit, copy or commit source files inside the Docker container. The deploy script installs a hook that refuses commits there.
- Deploy by copying files or by creating "mirror" commits in Docker. This is what split local and Docker history from 2026-09-15 to 2026-09-18 (reconciled in merge 51578c1).
- Work around a refusal from the deploy script. If it says Docker diverged or is dirty: bring the Docker changes into the local repo (git bundle + merge), commit locally, then deploy. If it says a commit has encrypted or non-UTF-8 files: fix them locally and commit again.
