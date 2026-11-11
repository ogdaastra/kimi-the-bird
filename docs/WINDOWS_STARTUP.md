# Starting Kimi automatically when you log in (optional)

Kimi runs on **your** computer. It only lives while your PC is on and Kimi is
running; it does not run in the cloud. These steps make Kimi start when you
log in so it can keep living in the background. None of them need
administrator rights, and none change Windows security settings.

Before you start, install Kimi and run it once normally (`scripts\start_kimi.bat`)
so you can enter your API key on the setup screen.

## Option A - Task Scheduler (recommended)

1. Press **Start**, type **Task Scheduler**, and open it.
2. In the right-hand panel choose **Create Task…** (not "Create Basic Task").
3. **General** tab
   - Name: `Kimi`
   - Select **Run only when user is logged on**. (Kimi needs your login session
     to read its key from Windows Credential Manager.)
   - Leave **Run with highest privileges** unticked. Kimi never needs admin rights.
4. **Triggers** tab → **New…**
   - Begin the task: **At log on**
   - Settings: **Specific user** (your account)
   - Optional: tick **Delay task for** `1 minute` so Windows finishes starting first.
5. **Actions** tab → **New…**
   - Action: **Start a program**
   - Program/script: the full path to `pythonw.exe` inside Kimi's folder, e.g.
     `C:\Users\you\kimi-the-bird\.venv\Scripts\pythonw.exe`
   - Add arguments: `main.py` (for the window) or `main.py --headless` (no window)
   - Start in: Kimi's folder, e.g. `C:\Users\you\kimi-the-bird`
6. **Conditions** tab: untick **Start the task only if the computer is on AC power**
   if you use a laptop and want Kimi to start on battery too.
7. **Settings** tab: untick **Stop the task if it runs longer than…** so Kimi is
   not stopped after three days. Choose **Do not start a new instance** under
   "If the task is already running".
8. Click **OK**. To test it, right-click the task and choose **Run**.

If Task Scheduler reports "Access is denied" on your PC (some managed or work
computers restrict it), use Option B instead.

## Option B - Startup folder

1. Press **Win + R**, type `shell:startup`, and press Enter.
2. Right-click in the folder → **New → Shortcut**.
3. For the location, browse to `scripts\start_kimi.bat` in Kimi's folder.
4. Name it `Kimi` and finish.

## Stopping or removing auto-start

- Task Scheduler: right-click the **Kimi** task → **Disable** or **Delete**.
- Startup folder: delete the shortcut from `shell:startup`.

## Notes

- Only one copy of Kimi can use a world at a time; a second copy exits politely.
- Kimi saves its world every few seconds and on shutdown, and recovers from the
  last save if the PC loses power.
- Kimi's world clock only moves while Kimi is running. When you log back in,
  Kimi picks up exactly where it left off.
- Headless mode writes a log to `data\logs\kimi.log`. To see Kimi's world, run
  the normal app (close the headless copy first).
