# File-Write Encryption on This Machine (HARD RULE)

This rule applies to every coding agent working in this repository (Codex, Claude Code, others). It is the same rule as section 5 of CLAUDE.md; keep both in sync.

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
- Native agent file tools: Codex `apply_patch` / edit tools, Claude Code `Write` / `Edit` / `NotebookEdit`.
- `cmd.exe /c "type SRC > DEST"` (this is what encrypted PreRequestCenter.vue / PriceApprovalWorkbench.vue on 2026-09-16), and any cmd command that reads a file and redirects it.
- WSL writes, e.g. `wsl ... sh -c 'cat SRC > DEST'`.
- Bash `>` / heredoc / `sed -i` / `awk` redirects, PowerShell `Set-Content` / `Out-File` / `[IO.File]::WriteAllText`.
- Local `node` / `vite build` / `yarn build` (build and test inside Docker instead).

Verify EVERY write with git, never with python (python may see decrypted bytes):
- `git diff --numstat -- <path>` must show line counts, not `-  -` / `Bin`; or `git hash-object --no-filters <path>` equals the expected hash.
- If a file turns out encrypted: stop and tell the user. Do not commit it and do not deploy it.

Reading: `cmd.exe type` of a protected file may return ciphertext and does NOT decrypt. An already-encrypted file that is unchanged from Git can be restored with `git checkout -- <path>` (only with the user's go-ahead). The real long-term fix is IT: mark `D:\rayher` as a plaintext directory in TipRay, or trust the development processes by name.
