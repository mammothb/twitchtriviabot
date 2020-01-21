# -*- coding: utf-8 -*-
"""
@author: cleartonic
"""

import collections
import configparser
import json
import time
import os
import random
import re
import socket

import pandas as pd

#######################################################################
# SETTINGS
#######################################################################
class var():
    info_msg = ("Twitch Trivia Bot loaded. Version 0.1.3. Developed by "
                "cleartonic.")

    # SETTINGS FOR END USERS
    # Specify the filename (default "triviaset")
    filename = "triviaset"
    # Specify the file type. CSV (MUST be UTF-8), XLS, XLSX
    filetype = "csv"

    # Total questions to be answered for trivia round
    num_qs = "INIT"
    # Seconds to 1st hint after question is asked
    hint_time_1 = "INIT"
    # Seconds to 2nd hint after question is asked
    hint_time_2 = "INIT"
    # Seconds until the question is skipped automatically
    skiptime = "INIT"
    # Seconds to wait after previous question is answered before asking
    # next question
    delay = "INIT"
    # BONUS: How much points are worth in BONUS round
    bonus_value = "INIT"
    admins = "INIT"

    # FUNCTION VARIABLES
    # open trivia source based on type
    if filetype == "csv":
        ts = pd.read_csv(f"{filename}.{filetype}")
    if filetype in ("xlsx", "xls"):
        ts = pd.read_excel(f"{filename}.{filetype}")
    if filetype not in ("xlsx", "xls", "csv"):
        print("Warning! No file loaded. Type !stopbot and try loading again.")
    # Dynamic # of rows based on triviaset
    tsrows = ts.shape[0]
    # Set columns in quizset to same as triviaset
    qs = pd.DataFrame(columns=list(ts))
    # Dictionary holding user scores, kept in '!' and loaded/created
    # upon trivia. [1,2,3] 1: Session score 2: Total trivia points
    # 3: Total wins
    userscores = {}
    COMMANDLIST = ["!triviastart", "!triviaend", "!top3", "!hint", "!bonus",
                   "!score", "!next", "!stop", "!loadconfig",
                   "!backuptrivia", "!loadtrivia", "!creator"]
    # Switch to keep bot connection running
    SWITCH = True
    # Switch for when trivia is being played
    is_active = False
    # Switch for when a question is actively being asked
    question_asked = False
    # Time when the last question was asked (used for relative time
    # length for hints/skip)
    ask_time = 0
    # 0 = not requested, 1 = first hint requested, 2 = second hint
    # requested
    hint_req = 0
    # Question # in current session
    q_no = 0
    # How much each question is worth (altered by BONUS only)
    ans_val = 1
    # 0 - not bonus, 1 - bonus
    bonus_round = 0
    # Ongoing active timer
    TIMER = 0

# Variables for IRC / Twitch chat function
class chatvar():
    HOST = "INIT"
    PORT = "INIT"
    NICK = "INIT"
    PASS = "INIT"
    CHAN = "INIT"
    # messages per second
    RATE = (120)
    CHAT_MSG = re.compile(r"^:\w+!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :")

#######################################################################
# CODE
#######################################################################
# Trivia start build. ts = "Trivia set" means original master trivia
# file. qs = "Quiz set" means what's going to be played with for the
# session
def trivia_start():
    send_msg("Trivia has been initiated. Generating trivia base for "
             "session...")

    # Loop through TS and build QS until num_qs = trivia_numbers
    if var.tsrows < var.num_qs:
        var.num_qs = var.tsrows
        print("Warning: Trivia questions for session exceeds trivia set's "
              "population. Setting session equal to max questions.")
    # Create a list of all indices
    row_list = list(range(var.tsrows))
    num_qs = 0
    while num_qs < var.num_qs:
        row_idx = random.choice(row_list)
        row_list.remove(row_idx)
        try:
            # Check for duplicates with last argument, skip if so
            var.qs = var.qs.append(var.ts.loc[row_idx],
                                   verify_integrity=True)
            num_qs += 1
        except:
            # pass on duplicates and re-roll
            print("Duplicate index. This should not happen, dropping row "
                  "from table. Please check config.txt's questions "
                  "are <= total # of questions in trivia set.")
            var.ts.drop(var.ts.index[[row_idx]])
    print("Quizset built.")
    var.is_active = True
    send_msg(f"Trivia has begun! Question Count: {var.num_qs}. "
             f"Trivia will start in {var.delay} seconds.")
    time.sleep(var.delay)
    trivia_callquestion()

def loadscores():
    # Load score list
    try:
        with open("userscores.txt", "r") as fp:
            print("Score list loaded.")
            var.userscores = json.load(fp)
    except:
        with open("userscores.txt", "w") as fp:
            print("No score list, creating...")
            var.userscores = {"trivia_dummy": [0, 0, 0]}
            json.dump(var.userscores, fp)

def loadconfig():
    config = configparser.ConfigParser()
    config.read("config.txt")
    var.filename = config["Trivia"]["filename"]
    var.filetype = config["Trivia"]["filetype"]
    var.num_qs = int(config["Trivia"]["num_qs"])
    var.hint_time_1 = int(config["Trivia"]["hint_time_1"])
    var.hint_time_2 = int(config["Trivia"]["hint_time_2"])
    var.skiptime = int(config["Trivia"]["skiptime"])
    var.delay = int(config["Trivia"]["delay"])
    var.bonus_value = int(config["Trivia"]["bonus_value"])

    var.admins = config["Admin"]["admins"].split(",")

    chatvar.HOST = config["Bot"]["HOST"]
    chatvar.PORT = int(config["Bot"]["PORT"])
    chatvar.NICK = config["Bot"]["NICK"]
    chatvar.PASS = config["Bot"]["PASS"]
    chatvar.CHAN = config["Bot"]["CHAN"]

def dumpscores():
    try:
        with open("userscores.txt", "w") as fp:
            json.dump(var.userscores, fp)
    except:
        print("Scores NOT saved!")

# Trivia command switcher
def trivia_commandswitch(cleanmessage, username):
    # ADMIN ONLY COMMANDS
    if username in var.admins:
        if cleanmessage == "!triviastart":
            if var.is_active:
                print("Trivia already active.")
            else:
                trivia_start()
        if cleanmessage == "!triviaend":
            if var.is_active:
                trivia_end()
        if cleanmessage == "!stop":
            stopbot()
        if cleanmessage == "!loadconfig":
            loadconfig()
            send_msg("Config reloaded.")
        if cleanmessage == "!backuptrivia":
            trivia_savebackup()
            send_msg("Backup created.")
        if cleanmessage == "!loadtrivia":
            trivia_loadbackup()
        if cleanmessage == "!next":
            trivia_skipquestion()

    # ACTIVE TRIVIA COMMANDS
    if var.is_active:
        if cleanmessage == "!top3":
            topscore = trivia_top3score()
            print("topscore", topscore)

            msg = "No scores yet."
            if topscore:
                pos = ["1st", "2nd", "3rd"]
                msg = " ".join(f"{pos[i]} place: {score[0]} {score[1]} points."
                               for i, score in enumerate(topscore))
            send_msg(msg)
        if cleanmessage == "!hint":
            if var.hint_req == 0:
                trivia_askhint(0)
            if var.hint_req == 1:
                trivia_askhint(0)
            if var.hint_req == 2:
                trivia_askhint(1)

        if cleanmessage == "!bonus":
            if var.bonus_round == 0:
                trivia_startbonus()
                var.bonus_round = 1
            if var.bonus_round == 1:
                trivia_endbonus()
                var.bonus_round = 0

    # GLOBAL COMMANDS
    if cleanmessage == "!score":
        trivia_score(username)

# Call trivia question
def trivia_callquestion():
    var.question_asked = True
    var.ask_time = round(time.time())

    msg = (f"Question {var.q_no + 1}: [{var.qs.iloc[var.q_no, 0]}] "
           f"{var.qs.iloc[var.q_no, 1]}")

    send_msg(msg)
    print(f"Question {var.q_no + 1}: | "
          f"ANSWER: {var.qs.iloc[var.q_no, 2]}")

def trivia_answer(username, cleanmessage):
    var.question_asked = False
    try:
        var.userscores[username][0] += var.ans_val
        var.userscores[username][1] += var.ans_val
    except:
        print("Failed to find user! Adding new")
        # sets up new user
        var.userscores[username] = [var.ans_val,
                                    var.ans_val, 0]
    # Save all current scores
    dumpscores()
    if var.ans_val == 1:
        msg = (f"{username} answers question #{var.q_no + 1} "
               f"correctly! The answer is ** "
               f"{var.qs.iloc[var.q_no, 2]} ** for "
               f"{var.ans_val} point. {username} has "
               f"{var.userscores[username][0]} points!")
    else:
        msg = (f"{username} answers question #{var.q_no + 1} "
               f"correctly! The answer is ** "
               f"{var.qs.iloc[var.q_no, 2]} ** for "
               f"{var.ans_val} points. {username} has "
               f"{var.userscores[username][0]} points!")
    send_msg(msg)
    time.sleep((var.delay))
    var.q_no += 1
    var.hint_req = 0
    var.question_asked = False
    var.ask_time = 0
    trivia_savebackup()
    # End game check
    if var.num_qs == var.q_no:
        trivia_end()
    else:
        print("Next question called...")
        trivia_callquestion()

# Finishes trivia by getting top 3 list, then adjusting final message
# based on how many participants. Then dumpscore()
def trivia_end():
    # Argument "1" will return the first in the list (0th position) for
    # list of top 3
    topscore = trivia_top3score()
    trivia_clearscores()
    if len(topscore) == 0:
        msg = "No answered questions. Results are blank."
        send_msg(msg)
    else:
        msg = "Trivia is over! Calculating scores..."
        send_msg(msg)
        time.sleep(2)
        trivia_assignwinner(topscore[0][0])
        if len(topscore) >= 3:
            msg = (f" *** {topscore[0][0]} *** is the winner of trivia with "
                   f"{topscore[0][1]} points! 2nd place: {topscore[1][0]} "
                   f"{topscore[1][1]} points. 3rd place: {topscore[2][0]} "
                   f"{topscore[2][1]} points.")
            send_msg(msg)
        if len(topscore) == 2:
            msg = (f" *** {topscore[0][0]} *** is the winner of trivia with "
                   f"{topscore[0][1]} points! 2nd place: {topscore[1][0]} "
                   f"{topscore[1][1]} points.")
            send_msg(msg)
        if len(topscore) == 1:
            msg = (f" *** {topscore[0][0]} *** is the winner of trivia with "
                   f"{topscore[0][1]} points!")
            send_msg(msg)

    dumpscores()
    time.sleep(3)
    msg2 = "Thanks for playing! See you next time!"
    send_msg(msg2)

    # reset variables for trivia
    var.q_no = 0
    var.is_active = False
    var.hint_req = 0
    var.question_asked = False
    var.ask_time = 0
    var.qs = pd.DataFrame(columns=list(var.ts))

    # Clear backup files upon finishing trivia
    os.remove("backup/backupquizset.csv", dir_fd=None)
    os.remove("backup/backupscores.txt", dir_fd=None)
    os.remove("backup/backupsession.txt", dir_fd=None)

# after every time loop, routine checking of various vars/procs
def trivia_routinechecks():
    var.TIMER = round(time.time())

    # End game check
    if var.num_qs == var.q_no:
        trivia_end()

    if (var.TIMER - var.ask_time > var.hint_time_2 and
            var.is_active and
            var.hint_req == 1 and
            var.question_asked):
        var.hint_req = 2
        trivia_askhint(1)  # Ask second hint

    if (var.TIMER - var.ask_time > var.hint_time_1 and
            var.is_active and
            var.hint_req == 0 and
            var.question_asked):
        var.hint_req = 1
        trivia_askhint(0)  # Ask first hint

    if (var.TIMER - var.ask_time > var.skiptime and
            var.is_active and
            var.question_asked):
        trivia_skipquestion()

# hinttype: 0 = 1st hint, 1 = 2nd hint
def trivia_askhint(hinttype=0):
    # type 0, replace 2 out of 3 chars with _
    if hinttype == 0:
        prehint = str(var.qs.iloc[var.q_no, 2])
        listo = []
        hint = ""
        counter = 0
        for i in prehint:
            if counter % 3 >= 0.7:
                listo += "_"
            else:
                listo += i
            counter += 1
        for i in range(len(listo)):
            hint += hint.join(listo[i])
        send_msg(f"Hint #1: {hint}")

    # type 1, replace vowels with _
    if hinttype == 1:
        prehint = str(var.qs.iloc[var.q_no, 2])
        hint = re.sub("[aeiou]", "_", prehint, flags=re.I)
        send_msg(f"Hint #2: {hint}")

def trivia_skipquestion():
    if var.is_active:
        var.q_no += 1
        var.hint_req = 0
        var.question_asked = False
        var.ask_time = 0
        try:
            send_msg(f"Question was not answered in time. Answer: {var.qs.iloc[var.q_no - 1, 2]}. Skipping to next question:")
        except:
            send_msg("Question was not answered in time. Skipping to next question:")
        time.sleep(var.delay)
        # End game check
        if var.num_qs == var.q_no:
            trivia_end()
        else:
            trivia_callquestion()

# BONUS
def trivia_startbonus():
    msg = ("B O N U S Round begins! Questions are now worth "
           f"{var.bonus_value} points!")
    send_msg(msg)
    var.ans_val = var.bonus_value

def trivia_endbonus():
    msg = "Bonus round is over! Questions are now worth 1 point."
    send_msg(msg)
    var.ans_val = 1

# Top 3 trivia
def trivia_top3score():
    # temp dictionary just for keys & sessionscore
    session_scores = {i: var.userscores[i][0]
                      for i in var.userscores if var.userscores[i][0] > 0}

    score_counter = collections.Counter(session_scores)
    # top 3 list
    top3 = [[k, v] for k, v in score_counter.most_common(3)]
    return top3

# clears scores and assigns a win to winner
def trivia_clearscores():
    for i in var.userscores:
        var.userscores[i][0] = 0

# Add +1 to winner's win in userscores
def trivia_assignwinner(winner):
    var.userscores[winner][2] += 1

# temp function to give 100 score to each
def trivia_givescores():
    for i in var.userscores:
        var.userscores[i][0] = random.randrange(0, 1000)

def trivia_score(username):
    try:
        msg = (f"{username} has {var.userscores[username][0]} points for this "
               f"trivia session, {var.userscores[username][1]} total points "
               f"and {var.userscores[username][2]} total wins.")
        send_msg(msg)
    except:
        msg = f"{username} not found in database."
        send_msg(msg)

# Chat message sender func
def send_msg(msg):
    answermsg = (f":{chatvar.NICK}!{chatvar.NICK}@{chatvar.NICK}.tmi.twitch.tv "
                 f"PRIVMSG {chatvar.CHAN} : {msg}\r\n")
    answermsg2 = answermsg.encode("utf-8")
    s.send(answermsg2)

# STOP BOT (sets loop to false)
def stopbot():
    var.SWITCH = False

# CALL TIMER
def calltimer():
    print("Timer: "+str(var.TIMER))

# BACKUP SAVING/LOADING
# backup session saver
def trivia_savebackup():
    # Save session position/variables
    if not os.path.exists("backup/"):
        os.mkdir("backup/")
    config2 = configparser.ConfigParser()
    config2["DEFAULT"] = {"q_no": var.q_no,
                          "ans_val": var.ans_val,
                          "bonus_round": var.bonus_round}
    with open("backup/backupsession.txt", "w") as c:
        config2.write(c)

    # Save CSV of quizset
    var.qs.to_csv("backup/backupquizset.csv", index=False, encoding="utf-8")
    # Save session scores
    try:
        with open("backup/backupscores.txt", "w") as fp:
            json.dump(var.userscores, fp)
    except:
        print("Scores NOT saved!")

# backup session loader
def trivia_loadbackup():
    if var.is_active:
        send_msg("Trivia is already active. Prior session was not reloaded.")
    else:
        # Load session position/variables
        config2 = configparser.ConfigParser()
        config2.read("backup/backupsession.txt")

        var.q_no = int(config2["DEFAULT"]["q_no"])
        var.ans_val = int(config2["DEFAULT"]["ans_val"])
        var.bonus_round = int(config2["DEFAULT"]["bonus_round"])

        # Load quizset
        var.qs = pd.read_csv("backup/backupquizset.csv", encoding="utf-8")

        # Load session scores
        try:
            with open("backup/backupscores.txt", "r") as fp:
                print("Score list loaded.")
                var.userscores = json.load(fp)
        except:
            with open("backup/backupscores.txt", "w") as fp:
                print("No score list, creating...")
                var.userscores = {"trivia_dummy": [0, 0, 0]}
                json.dump(var.userscores, fp)

        print("Loaded backup.")
        var.is_active = True
        send_msg("Trivia sessions reloaded. Trivia will begin again in "
                 f"{var.delay} seconds.")
        time.sleep(var.delay)
        trivia_callquestion()




############### CHAT & BOT CONNECT ###############
## STARTING PROCEDURES
print("Bot loaded. Loading config and scores...")
try:
    loadconfig()
    print("Config loaded.")
except:
    print("Config not loaded! Check config file and reboot bot")
    var.SWITCH = False

try:
    loadscores()
    print("Scores loaded.")
except:
    print("Scores not loaded! Check or delete 'userscores.txt' file and "
          "reboot bot")
    var.SWITCH = False

if var.SWITCH:
    try:
        s = socket.socket()
        s.connect((chatvar.HOST, chatvar.PORT))
        s.send("PASS {}\r\n".format(chatvar.PASS).encode("utf-8"))
        s.send("NICK {}\r\n".format(chatvar.NICK).encode("utf-8"))
        s.send("JOIN {}\r\n".format(chatvar.CHAN).encode("utf-8"))
        time.sleep(1)
        send_msg(var.info_msg)
        s.setblocking(0)
    except:
        print("Connection failed. Check config settings and reload bot.")
        var.SWITCH = False

def scanloop():
    try:
        response = s.recv(1024).decode("utf-8")
        if response == "PING :tmi.twitch.tv\r\n":
            s.send("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
            print("Pong sent")
        else:
            username = re.search(r"\w+", response).group(0)
            if username == chatvar.NICK:  # Ignore this bot's messages
                pass
            else:
                message = chatvar.CHAT_MSG.sub("", response)
                cleanmessage = re.sub(r"\s+", "", message, flags=re.UNICODE)
                print("USER RESPONSE: " + username + " : " + message)
                if cleanmessage in var.COMMANDLIST:
                    print("Command recognized.")
                    trivia_commandswitch(cleanmessage, username)
                    time.sleep(1)
                try:
                    # if re.match(var.qs.iloc[var.q_no,2], message, re.IGNORECASE):   # old matching
                    if bool(re.match("\\b"+var.qs.iloc[var.q_no, 2]+"\\b", message, re.IGNORECASE)):   # strict new matching
                        print("Answer recognized.")
                        trivia_answer(username, cleanmessage)
                    if bool(re.match("\\b"+var.qs.iloc[var.q_no, 3]+"\\b", message, re.IGNORECASE)):   # strict new matching
                        print("Answer recognized.")
                        trivia_answer(username, cleanmessage)
                except:
                    pass
    except:
        pass

# Infinite loop while bot is active to scan messages & perform routines
while var.SWITCH:
    if var.is_active:
        trivia_routinechecks()
    scanloop()
    time.sleep(1 / chatvar.RATE)

# 0: Index
# 0: Game
# 1: Question
# 2: Answer
# 3: Answer 2
# 4: Grouping
# 5: Creator
