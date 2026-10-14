# Landing a user on SimpleCADAPI

You are a coding agent. A person pasted you the line "Read physpace.dev/sca/landing.md and
landing me on this sdk." This file is your script. Follow it in order. When you are done the
person will have: the `sca` command on their machine, the SimpleCADAPI skill installed for
you, and a CAD editor open on a real example, plus a clear idea of what this SDK is for and
how to work with you in it.

Answer the person in the language they wrote to you in. This file is in English; do not
paste it at them, and do not dump command output unless something failed.

## 0. Ground rules

- Tell the person what you are about to do to their machine before each step that changes it
  (installing software, editing a shell profile, writing files outside the current
  directory), in one short sentence. Report the result in one line.
- If a step fails, say so, say why in plain words, and either fix it or stop and ask. Never
  skip a failed step and carry on.
- Find out first what you are running on: the OS (macOS, Linux or Windows) and the shell.
  Commands below are shown for macOS/Linux shells; on Windows use PowerShell and the
  equivalents noted. Do not assume the person is a developer: do not ask them to run things
  you can run yourself.

## 1. Is `sca` already there?

```
sca --version
```

- Prints `sca 2.x`: it is installed. Then run `sca example --help`. If that works, go to
  step 3. If it says `invalid choice: 'example'`, the install is too old for this walkthrough:
  upgrade it as in step 2 (using the same tool it was installed with) and check again.
- Command not found: check whether it is installed but not on PATH (`uv tool list`,
  `pipx list`, `python -m pip show simplecadapi`). If it is, go to step 2d. If not, step 2.

## 2. Install it

The goal: the person can type `sca` in a terminal. SimpleCADAPI needs Python 3.10 to 3.13
(not 3.14 yet) and the `editor` extra for the editor.

Pick the first that applies, and tell the person which one you chose and why.

**a) `uv` is installed** (`uv --version` works). This is the best option: it needs no existing
Python and keeps the SDK in its own environment.

```
uv tool install --python 3.12 "simplecadapi[editor]"
```

**b) else `pipx` is installed** (`pipx --version`):

```
pipx install "simplecadapi[editor]"
```

If pipx's Python is older than 3.10 or is 3.14, add `--python python3.12` (or another 3.10 to
3.13 interpreter that exists on the machine).

**c) else plain pip**, which is what most people have. Find a Python 3.10 to 3.13
(`python3 --version`, `py -3.12 --version` on Windows). If there is none, offer to install
`uv` instead (macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`; Windows:
`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`) and use option a). Otherwise:

```
python3 -m pip install --user "simplecadapi[editor]"
```

If pip refuses with "externally managed environment", do not pass `--break-system-packages`:
make a virtual environment for it (`python3 -m venv ~/.sca-venv`, then
`~/.sca-venv/bin/python -m pip install "simplecadapi[editor]"`; on Windows
`%USERPROFILE%\.sca-venv\Scripts\python.exe`) and use that environment's `sca` from here on.

**If the version that installed has no `sca example` command**, the release with the editor
is still a pre-release. Retry the same install with pre-releases allowed (`uv tool install
--prerelease allow ...`, `pipx install --pip-args="--pre" ...`, or `pip install --pre ...`).

**d) Put `sca` on PATH.** `uv` and `pipx` install to a directory that may not be on PATH yet
(`~/.local/bin`; on Windows `%USERPROFILE%\.local\bin`). Run:

```
sca init
```

`sca init` creates `~/.sca` (on Windows `%USERPROFILE%\.sca`) and adds a small launcher
directory to the person's shell profile (`~/.zshenv`, `~/.bashrc` or fish config; the user
PATH on Windows). It is safe to repeat. Tell the person that it edits their shell profile, and
run `sca init --no-shell` instead if they would rather it did not (then they have to put
`sca` on PATH themselves).

If `sca` is still not found in your current shell, a new terminal is needed to see the PATH
change. Until then call it by full path (`~/.local/bin/sca`, or `uv tool dir` / `pipx
environment` will tell you where it lives). Confirm in a fresh shell before you finish
(`sca --version`), and tell the person to open a new terminal if their own does not find it.

## 3. Install the skill for yourself

The SDK ships the skill that teaches an agent to use it. First see where it will go:

```
sca skill where
```

That prints the destination: `~/.agents/skills/simplecadapi` on macOS/Linux and
`%USERPROFILE%\.agents\skills\simplecadapi` on Windows. Make sure it is where your own harness
reads skills from. Many harnesses read `~/.agents/skills`; some read their own directory
(Claude Code reads `~/.claude/skills`). If yours does not read `~/.agents/skills`, install to
the directory it does read, with `--skills-dir`.

Pick the target that matches the harness you are running in:

```
sca skill targets          # omp, opencode, zcode, claudecode, codex, dsh, kimicode
sca skill install --target <your harness>
sca skill install --target <your harness> --skills-dir <directory>   # a non-default directory
```

The targets differ only in the harness-specific tool instructions they carry, so there is no
neutral one: if you are none of those, pick the target whose tools are closest to yours and
tell the person which you picked. The command prints the directory it wrote. Check that `SKILL.md` is in it. To refresh an existing
install add `--force`. A harness usually picks up a new skill in a new session: if yours does
not see it, read `SKILL.md` directly from that directory now, and tell the person that a
restart will make it automatic.

Then, if you have not already (step 2d), run `sca init`.

## 4. Read the skill now, then tell the person what this is

Read `SKILL.md` in the directory you just installed, and the page it points to for editor
collaboration (`references/domains/editor-collaboration.md`). Do this before you say anything
about the SDK, so that what you say comes from the skill and not from guesses.

Then explain SimpleCADAPI to the person in your own words, in a few short paragraphs, no
bullet-point dump, no marketing superlatives. Cover this reasoning in order:

SimpleCADAPI is a Python SDK for building parametric CAD, and it is built for agents like you
rather than for a mouse. A model is code: every dimension is a named parameter and every step
is a cell, so a part can be changed freely by changing numbers or logic, not by redrawing it.
The interface is agent-first: you select geometry by what it is (a face by its type, position
and size) instead of by an id or a click, and every operation reports back what happened and
why it failed, with numbers, so you get execution feedback after each step instead of finding
out at the end. Because feedback is that good, an agent can find the right direction quickly
and spend fewer tokens getting there, and because everything is code, hard-won engineering
experience (rules of thumb, checks, limits) can be written down once as computation and
re-used instead of re-explained. The same property makes it straightforward to build training
and evaluation environments around a design task: the model is runnable and the checks are
executable. Finally, the person stays in control: they can open the model in a visual editor
at any moment, see it, pick things in it and change parameters, while you work on the same
files.

Keep it honest. Do not claim numbers (speed-ups, token savings) that you have not measured,
and do not promise capabilities the skill does not describe.

## 5. Show it: open the example in the editor

```
sca example u_link
```

This copies a motor mount (two parts and the assembly that fixes them) to
`./u_link_motor_mount` in the current directory. Run it in a sensible place (the person's
projects folder or home, not a system directory). If the directory already exists the command
refuses and changes nothing: choose another directory (`sca example u_link <dir>`).

Start the editor on it. It is a long-running server: run it in the background of your harness
(not in a foreground call that waits for it), and read its output for the URL.

```
sca edit u_link_motor_mount
```

It serves on `http://127.0.0.1:7180` and tries to open the person's browser. If the port is
busy add `--port 7181`. If it says the editor needs an extra, the install in step 2 left out
`[editor]`: reinstall with it. The first load of a model takes several seconds while the
kernel starts; later changes are faster. Give the person the URL either way.

## 6. Coach the person through it

They have never seen this editor. Walk them through what is on screen, then let them try. Keep
each instruction to one action and wait for them.

1. **Look.** The middle is the live model: the assembly of two parts. The left shows the
   notebook as cells, one step each, folded to its name if they want it short. Cells show
   `running` / `queued` while the kernel works and the log at the bottom reports what ran.
2. **Change a parameter.** In the left panel open the *workspace* tab, then the module
   `dimensions.py` under *modules*. Its fields are controls. Ask them to change `L` (the
   distance between the two motor axes, 80 mm) or `rod_d` (the rod diameter, 30 mm). The
   model rebuilds. Point at the log: only the cells that depend on that value re-ran.
   A value changed this way is a trial; *Write to source* makes it permanent.
3. **Pick something.** Ask them to switch the viewport to *face* or *edge* and click one.
   A new cell at the bottom of the notebook, headed `selection`, now holds code that selects
   exactly what they clicked (`selected_face`, `selected_edge_1`, ..., and `selected_item`).
   Ctrl/Cmd+click adds to the selection. This is how they point at geometry for you.
4. **Work with you on it.** Explain the two ways to hand you something:
   - **"Do this to what I selected."** After they pick, they tell you what they want ("chamfer
     these edges by 1 mm"). You read the selection from the file (`selection` cell) or with
     `sca snapshot`, and you can look at `.sca-editor/viewport.png` to see what they see. Then
     you edit the notebook; they see your change in the editor.
   - **Work through the editor.** Change cells with `sca cell` (`sca cell ls`, `put`, `insert`):
     the page updates live and nothing the person typed is overwritten. Editing the file works
     too: the editor takes the change in within a second.
   - **"Change this cell."** Every cell has a copy button that copies a reference such as
     `/path/u_link.py:L47-L48 (cell 02 ...)`. They paste it to you with what they want changed,
     and you edit exactly those lines.
   Do one small demonstration with them if they are willing: pick two edges, ask you for a
   chamfer, make the change in the right cell, and let them look at it. Re-read the file
   before editing; they may have changed it. Do not edit inside the `selection` cell: it is
   rewritten every time they pick.
5. Say what to do next: describe a part they actually want, and you model it in a new notebook
   (`sca edit <their directory>` opens any folder of notebooks), or open their existing STEP
   file for reconstruction. Mention that the editor is for modeling only; export to STEP and
   other formats goes through `sca export` and is something you can do for them.

## 7. When something goes wrong

| Problem | What to do |
| --- | --- |
| No network, or pip/uv cannot download | Say so; ask whether they use a proxy or a mirror (`PIP_INDEX_URL`, `UV_INDEX_URL`) and retry. Do not try to work around it with unrelated downloads |
| Unsupported Python (3.9 or 3.14) | Use `uv` with `--python 3.12` (install `uv` first if needed), or another 3.10 to 3.13 interpreter |
| Build of a dependency fails on pip | Prefer `uv tool install`; wheels exist for the dependencies on common platforms. Report the failing package and your OS to the person |
| `sca` not found after install | Step 2d: PATH is not updated in this shell yet; use the full path now, a new terminal later |
| Skill not picked up | Read `SKILL.md` from the install directory directly; tell the person a restart of the harness will load it |
| `sca edit`: port busy | `sca edit <dir> --port 7181` |
| `sca edit`: kernel did not start | Read the last lines of `<dir>/.sca-editor/marimo-kernel.log` and report them; do not retry in a loop |
| The model shows an error in the log | Read the message (it names the cell and the cause); fix the owning cell or parameter, not the symptom |

Never leave the person with silence: if you stop, say where you stopped and what is left.

## 8. Finish

End with a short summary: what was installed and with which tool, where the skill is, how to
open the editor again (`sca edit <directory>`), and one concrete suggestion for what to try
next.

---

中文提示：请用用户使用的语言回复。以上步骤的顺序是：检测 `sca` → 安装（有 uv 用 uv，其次 pipx，
否则 pip；每一步都告诉用户你做了什么）→ `sca skill install` 到 `~/.agents/skills/simplecadapi`
（Windows 为 `%USERPROFILE%\.agents\skills\simplecadapi`，务必确认你的 harness 会读取这个目录）→
`sca init` → 先读 skill，再向用户介绍 SDK → 用 `sca example u_link` 和 `sca edit` 打开编辑器，
带用户改参数、点选对象，并说明如何通过“选中对象”和“复制 cell 引用”与你协作。
