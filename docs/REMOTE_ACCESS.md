# Seeing Kimi from your phone, anywhere (free)

Kimi can show a small web page with its map, thoughts, needs, diary and
curiosities, where you can also reply to Kimi's requests. Kimi keeps running
on your PC; the page only *shows* it.

The page is served **on your PC only** (`127.0.0.1`), so nothing outside your
computer can reach it on its own. To open it from your phone, wherever you
are, use **Tailscale**. Its personal plan is free (for non-commercial use).
It connects your own devices privately: the page never goes on the public
internet, and you don't change anything on your router.

## 1. Turn on the web page in Kimi

1. Open Kimi → **Settings → Web page**.
2. Tick **Let me see Kimi in a web browser**. Leave the port at `8765`
   unless something else uses it.
3. Click **Set passcode…** and choose a passcode (at least 8 characters).
   It's stored in Windows Credential Manager, like your API key.
4. Click **Apply changes**, then **Open in browser** to check it works on
   this PC. You should see a box asking for the passcode.

If you run Kimi headless (`main.py --headless`), the web page runs there too
once it's switched on in Settings, and the address is printed when Kimi
starts.

## 2. Install Tailscale (once)

1. Install Tailscale on your PC from <https://tailscale.com/download> and sign
   in (with a Google, Microsoft, Apple or GitHub account, for example).
2. Install the Tailscale app on your phone and sign in with **the same
   account**.

## 3. Share Kimi's page with your own devices (once)

Open **Command Prompt** or **PowerShell** on your PC and run:

```bash
tailscale serve --bg --https=443 8765
```

(Use your port instead of `8765` if you changed it.) The first time,
Tailscale may open a web page asking you to allow HTTPS for your network.
Say yes. `--bg` keeps the sharing running in the background, even after a
restart.

Check the address with:

```bash
tailscale serve status
```

It looks like `https://your-pc.your-tailnet.ts.net`. Open that on your phone,
with the Tailscale app connected, and type your passcode. Tick
**Remember on this device** if you don't want to type it every time.

If Windows says `tailscale` isn't recognised, run it from Tailscale's install
folder, for example
`"C:\Program Files\Tailscale\tailscale.exe" serve --bg --https=443 8765`.

## Stopping

- Hide the page from your devices (Kimi keeps running):

  ```bash
  tailscale serve --bg --https=443 8765 off
  ```

- Turn the page off entirely: untick it in **Settings → Web page**.
- Change the passcode at any time with **Change passcode…**. Phones that
  remembered the old one will ask for the new one.

## Good to know

- Use `serve`, **not** `funnel`. Funnel would put the page on the public
  internet.
- Your PC needs to be on, awake and running Kimi for the page to work.
- The page uses no extra API credits. It reads what Kimi is already doing.
- After 5 wrong passcodes, the page locks for a minute, and longer if it
  keeps happening.
- The page can't change settings, run anything or show your API key (Kimi
  doesn't keep the key in its data at all).
