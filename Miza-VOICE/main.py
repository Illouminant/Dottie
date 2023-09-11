# Loads the install_update module, which makes sure all required libraries are installed to their required versions.
from install_update import *

# Makes sure an authentication file exists.
if not os.path.exists("auth.json") or not os.path.getsize("auth.json"):
    print("Authentication file not found. Generating empty template...")
    f = open("auth.json", "wb")
    d = {
        "prefix": "~",
        "python_path": "",
        "webserver_port": 9801,
        "discord_id": "",
        "discord_token": "",
        "owner_id": [],
        "google_api_key": "",
        "rapidapi_key": "",
        "genius_key": "",
        "alexflipnote_key": "",
        "papago_id": "",
        "papago_secret": "",
        "knack_id": "",
        "knack_secret": "",
    }
    s = "{\n" + repr(d).replace(" ", "").replace("'", '"').replace(",", ",\n")[1:-1] + "\n}"
    f.write(s.encode("utf-8"))
    f.close()
    input("auth.json generated. Please fill in discord_token and restart bot when done.")
    raise SystemExit


import time, datetime, psutil

# Required on Windows to display terminal colour codes? 🤔
if os.name == "nt":
    try:
        os.system("color")
    except:
        traceback.print_exc()


# Repeatedly attempts to delete a file, waiting 1 second between attempts.
def delete(f):
    while os.path.exists(f):
        try:
            os.remove(f)
            return
        except:
            traceback.print_exc()
        time.sleep(1)

sd = "shutdown.tmp"
rs = "restart.tmp"
hb = "heartbeat.tmp"
hb_ack = "heartbeat_ack.tmp"

delete(sd)


# Main watchdog loop.
att = 0
while not os.path.exists(sd):
    delete(rs)
    delete(hb)
    proc = psutil.Popen([python, "bot.py"], shell=True)
    start = time.time()
    print("Bot started with PID \033[1;34;40m" + str(proc.pid) + "\033[1;37;40m.")
    time.sleep(12)
    try:
        alive = True
        if proc.is_running():
            print("\033[1;32;40mHeartbeat started\033[1;37;40m.")
            while alive:
                if not os.path.exists(hb):
                    if os.path.exists(hb_ack):
                        os.rename(hb_ack, hb)
                    else:
                        with open(hb, "wb"):
                            pass
                print(
                    "\033[1;36;40m Heartbeat at "
                    + str(datetime.datetime.now())
                    + "\033[1;37;40m."
                )
                for i in range(32):
                    time.sleep(0.25)
                    ld = os.listdir()
                    if rs in ld or sd in ld:
                        alive = False
                        break
                if os.path.exists(hb):
                    break
            for child in proc.children():
                try:
                    child.kill()
                except:
                    traceback.print_exc()
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
            if os.path.exists(sd):
                break
        if time.time() - start < 30:
            att += 1
        else:
            att = 0
        if att > 16:
            print("\033[1;31;40mBot crashed 16 times in a row. Waiting 5 minutes before trying again.\033[1;37;40m")
            time.sleep(300)
            att = 0
        if alive:
            print("\033[1;31;40mBot failed to acknowledge heartbeat signal, restarting...\033[1;37;40m")
        else:
            print("\033[1;31;40mBot sent restart signal, advancing...\033[1;37;40m")
    except KeyboardInterrupt:
        raise
    except:
        traceback.print_exc()
    time.sleep(0.5)

if proc.is_running():
    try:
        for child in proc.children():
            child.kill()
    except:
        traceback.print_exc()
    proc.kill()
    
delete(sd)
delete(rs)
delete(hb)
delete(hb_ack)
        
print("Shutdown signal confirmed. Program will now terminate. ")
raise SystemExit