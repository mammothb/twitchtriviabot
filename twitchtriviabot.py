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

from editdistance import DistanceAlgorithm, EditDistance

POS = ["1st", "2nd", "3rd"]
#######################################################################
# SETTINGS
#######################################################################
class Var:
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
    COMMANDLIST = ["!triviastart", "!triviaend", "!top3", "!bonus", "!score",
                   "!next", "!stop", "!loadconfig", "!backuptrivia",
                   "!loadtrivia", "!creator"]
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
    # Distance comparer
    comparer = None

    @classmethod
    def is_game_over(cls):
        return cls.num_qs == cls.q_no

    @classmethod
    def exceed_time(cls, timing):
        return cls.TIMER - cls.ask_time > timing

# Variables for IRC / Twitch chat function
class ChatVar:
    HOST = "INIT"
    PORT = "INIT"
    NICK = "INIT"
    PASS = "INIT"
    CHAN = "INIT"
    # messages per second
    RATE = (120)
    CHAT_MSG = re.compile(r"^:\w+!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :")

#######################################################################
# Helper functions
#######################################################################
def fuzzy_match(idx, message):
    return (Var.comparer.compare(Var.qs.iloc[Var.q_no, idx].lower(),
                                 message.strip().lower(), 2 ** 31 - 1) /
            len(Var.qs.iloc[Var.q_no, idx]) < 0.4)

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
    if Var.tsrows < Var.num_qs:
        Var.num_qs = Var.tsrows
        print("Warning: Trivia questions for session exceeds trivia set's "
              "population. Setting session equal to max questions.")
    # Create a list of all indices
    row_list = list(range(Var.tsrows))
    num_qs = 0
    while num_qs < Var.num_qs:
        row_idx = random.choice(row_list)
        row_list.remove(row_idx)
        try:
            # Check for duplicates with last argument, skip if so
            Var.qs = Var.qs.append(Var.ts.loc[row_idx],
                                   verify_integrity=True)
            num_qs += 1
        except:
            # pass on duplicates and re-roll
            print("Duplicate index. This should not happen, dropping row "
                  "from table. Please check config.txt's questions "
                  "are <= total # of questions in trivia set.")
            Var.ts.drop(Var.ts.index[[row_idx]])
    print("Quizset built.")
    Var.is_active = True
    Var.comparer = EditDistance(DistanceAlgorithm.DAMERUAUOSA)
    send_msg(f"Trivia has begun! Question Count: {Var.num_qs}. "
             f"Trivia will start in {Var.delay} seconds.")
    time.sleep(Var.delay)
    trivia_callquestion()

def loadscores():
    # Load score list
    try:
        with open("userscores.txt", "r") as fp:
            print("Score list loaded.")
            Var.userscores = json.load(fp)
    except:
        with open("userscores.txt", "w") as fp:
            print("No score list, creating...")
            Var.userscores = {"trivia_dummy": [0, 0, 0]}
            json.dump(Var.userscores, fp)

def loadconfig():
    config = configparser.ConfigParser()
    config.read("config.txt")
    Var.filename = config["Trivia"]["filename"]
    Var.filetype = config["Trivia"]["filetype"]
    Var.num_qs = int(config["Trivia"]["num_qs"])
    Var.hint_time_1 = int(config["Trivia"]["hint_time_1"])
    Var.hint_time_2 = int(config["Trivia"]["hint_time_2"])
    Var.skiptime = int(config["Trivia"]["skiptime"])
    Var.delay = int(config["Trivia"]["delay"])
    Var.bonus_value = int(config["Trivia"]["bonus_value"])

    Var.admins = config["Admin"]["admins"].split(",")

    ChatVar.HOST = config["Bot"]["HOST"]
    ChatVar.PORT = int(config["Bot"]["PORT"])
    ChatVar.NICK = config["Bot"]["NICK"]
    ChatVar.PASS = config["Bot"]["PASS"]
    ChatVar.CHAN = config["Bot"]["CHAN"]

def dumpscores():
    try:
        with open("userscores.txt", "w") as fp:
            json.dump(Var.userscores, fp)
    except:
        print("Scores NOT saved!")

# Trivia command switcher
def trivia_commandswitch(cleanmessage, username):
    # ADMIN ONLY COMMANDS
    if username in Var.admins:
        if cleanmessage == "!triviastart":
            if Var.is_active:
                print("Trivia already active.")
            else:
                trivia_start()
        elif cleanmessage == "!triviaend" and Var.is_active:
            trivia_end()
        elif cleanmessage == "!stop":
            stopbot()
        elif cleanmessage == "!loadconfig":
            loadconfig()
            send_msg("Config reloaded.")
        elif cleanmessage == "!backuptrivia":
            trivia_savebackup()
            send_msg("Backup created.")
        elif cleanmessage == "!loadtrivia":
            trivia_loadbackup()
        elif cleanmessage == "!next":
            trivia_skipquestion()

    # ACTIVE TRIVIA COMMANDS
    if Var.is_active:
        if cleanmessage == "!top3":
            topscore = trivia_top3score()
            print("topscore", topscore)

            msg = "No scores yet."
            if topscore:
                msg = " ".join(f"{POS[i]} place: {score[0]} {score[1]} points."
                               for i, score in enumerate(topscore))
            send_msg(msg)

        if cleanmessage == "!bonus":
            if Var.bonus_round == 0:
                trivia_startbonus()
                Var.bonus_round = 1
            elif Var.bonus_round == 1:
                trivia_endbonus()
                Var.bonus_round = 0

    # GLOBAL COMMANDS
    if cleanmessage == "!score":
        trivia_score(username)

# Call trivia question
def trivia_callquestion():
    Var.question_asked = True
    Var.ask_time = round(time.time())

    send_msg(f"Question {Var.q_no + 1}: [{Var.qs.iloc[Var.q_no, 0]}] "
             f"{Var.qs.iloc[Var.q_no, 1]}")

    print(f"Question {Var.q_no + 1}: | ANSWER: {Var.qs.iloc[Var.q_no, 2]}")

def trivia_answer(username):
    Var.question_asked = False
    try:
        Var.userscores[username][0] += Var.ans_val
        Var.userscores[username][1] += Var.ans_val
    except:
        print("Failed to find user! Adding new")
        # sets up new user
        Var.userscores[username] = [Var.ans_val, Var.ans_val, 0]
    # Save all current scores
    dumpscores()
    send_msg(f"{username} answers question #{Var.q_no + 1} "
             f"correctly! The answer is ** "
             f"{Var.qs.iloc[Var.q_no, 2]} ** for "
             f"{Var.ans_val} point{'s' if Var.ans_val > 1 else ''}. "
             f"{username} has {Var.userscores[username][0]} points!")
    time.sleep((Var.delay))
    Var.q_no += 1
    Var.hint_req = 0
    Var.question_asked = False
    Var.ask_time = 0
    trivia_savebackup()

    if Var.is_game_over():
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
    msg = "No answered questions. Results are blank."
    if topscore:
        send_msg("Trivia is over! Calculating scores...")
        time.sleep(2)
        trivia_assignwinner(topscore[0][0])
        msg = "*** {} *** is the winner with {} points!".format(*topscore[0])
        for i, score in enumerate(topscore):
            if i > 0:
                msg += " {} place: {} {} points.".format(POS[i], *score)
    send_msg(msg)

    dumpscores()
    time.sleep(3)
    send_msg("Thanks for playing! See you next time!")

    # reset variables for trivia
    Var.q_no = 0
    Var.is_active = False
    Var.comparer = None
    Var.hint_req = 0
    Var.question_asked = False
    Var.ask_time = 0
    Var.qs = pd.DataFrame(columns=list(Var.ts))

    # Clear backup files upon finishing trivia
    os.remove("backup/backupquizset.csv", dir_fd=None)
    os.remove("backup/backupscores.txt", dir_fd=None)
    os.remove("backup/backupsession.txt", dir_fd=None)

# after every time loop, routine checking of various vars/procs
def trivia_routinechecks():
    Var.TIMER = round(time.time())

    if Var.is_game_over():
        trivia_end()

    if Var.is_active and Var.question_asked:
        if Var.exceed_time(Var.hint_time_2) and Var.hint_req == 1:
            Var.hint_req = 2
            trivia_askhint(1)  # Ask second hint
        elif Var.exceed_time(Var.hint_time_1) and Var.hint_req == 0:
            Var.hint_req = 1
            trivia_askhint(0)  # Ask first hint
        elif Var.exceed_time(Var.skiptime):
            trivia_skipquestion()

# hinttype: 0 = 1st hint, 1 = 2nd hint
def trivia_askhint(hinttype=0):
    prehint = Var.qs.iloc[Var.q_no, 2]
    if hinttype == 0:  # replace 2 out of 3 chars with _
        n = len(prehint)
        idx = random.sample(range(n), k=n // 3)
        hint = "".join(c if i in idx or not c.isalnum() else "_"
                       for i, c in enumerate(prehint))
        send_msg(f"Hint #1: {hint}")
    elif hinttype == 1:  # replace vowels with _
        hint = re.sub("[aeiou]", "_", prehint, flags=re.I)
        send_msg(f"Hint #2: {hint}")

def trivia_skipquestion():
    if Var.is_active:
        try:
            send_msg("Question was not answered in time. Answer: "
                     f"{Var.qs.iloc[Var.q_no, 2]}. Skipping to next question")
        except:
            send_msg("Question was not answered in time. Skipping to next "
                     "question")
        Var.q_no += 1
        Var.hint_req = 0
        Var.question_asked = False
        Var.ask_time = 0
        time.sleep(Var.delay)

        if Var.is_game_over():
            trivia_end()
        else:
            trivia_callquestion()

# BONUS
def trivia_startbonus():
    send_msg("B O N U S Round begins! Questions are now worth "
             f"{Var.bonus_value} points!")
    Var.ans_val = Var.bonus_value

def trivia_endbonus():
    send_msg("Bonus round is over! Questions are now worth 1 point.")
    Var.ans_val = 1

# Top 3 trivia
def trivia_top3score():
    # temp dictionary just for keys & sessionscore
    session_scores = {i: Var.userscores[i][0]
                      for i in Var.userscores if Var.userscores[i][0] > 0}

    score_counter = collections.Counter(session_scores)
    # top 3 list
    top3 = [[k, v] for k, v in score_counter.most_common(3)]
    return top3

# clears scores and assigns a win to winner
def trivia_clearscores():
    for i in Var.userscores:
        Var.userscores[i][0] = 0

# Add +1 to winner's win in userscores
def trivia_assignwinner(winner):
    Var.userscores[winner][2] += 1

# temp function to give 100 score to each
def trivia_givescores():
    for i in Var.userscores:
        Var.userscores[i][0] = random.randrange(0, 1000)

def trivia_score(username):
    try:
        send_msg(
            "{} has {} points for this trivia session, {} total points and "
            "{} total wins.".format(username, *Var.userscores[username]))
    except:
        send_msg(f"{username} not found in database.")

# Chat message sender func
def send_msg(msg):
    s.send(":{0}!{0}@{0}.tmi.twitch.tv PRIVMSG {1} : {2}\r\n".format(
        ChatVar.NICK, ChatVar.CHAN, msg).encode("utf-8"))

# STOP BOT (sets loop to false)
def stopbot():
    Var.SWITCH = False

# CALL TIMER
def calltimer():
    print(f"Timer: {Var.TIMER}")

#######################################################################
# BACKUP SAVING/LOADING
#######################################################################
# backup session saver
def trivia_savebackup():
    # Save session position/variables
    if not os.path.exists("backup/"):
        os.mkdir("backup/")
    config2 = configparser.ConfigParser()
    config2["DEFAULT"] = {"q_no": Var.q_no,
                          "ans_val": Var.ans_val,
                          "bonus_round": Var.bonus_round}
    with open("backup/backupsession.txt", "w") as c:
        config2.write(c)

    # Save CSV of quizset
    Var.qs.to_csv("backup/backupquizset.csv", index=False, encoding="utf-8")
    # Save session scores
    try:
        with open("backup/backupscores.txt", "w") as fp:
            json.dump(Var.userscores, fp)
    except:
        print("Scores NOT saved!")

# backup session loader
def trivia_loadbackup():
    if Var.is_active:
        send_msg("Trivia is already active. Prior session was not reloaded.")
    else:
        # Load session position/variables
        config2 = configparser.ConfigParser()
        config2.read("backup/backupsession.txt")

        Var.q_no = int(config2["DEFAULT"]["q_no"])
        Var.ans_val = int(config2["DEFAULT"]["ans_val"])
        Var.bonus_round = int(config2["DEFAULT"]["bonus_round"])

        # Load quizset
        Var.qs = pd.read_csv("backup/backupquizset.csv", encoding="utf-8")

        # Load session scores
        try:
            with open("backup/backupscores.txt", "r") as fp:
                print("Score list loaded.")
                Var.userscores = json.load(fp)
        except:
            with open("backup/backupscores.txt", "w") as fp:
                print("No score list, creating...")
                Var.userscores = {"trivia_dummy": [0, 0, 0]}
                json.dump(Var.userscores, fp)

        print("Loaded backup.")
        Var.is_active = True
        send_msg("Trivia sessions reloaded. Trivia will begin again in "
                 f"{Var.delay} seconds.")
        time.sleep(Var.delay)
        trivia_callquestion()

#######################################################################
# CHAT & BOT CONNECT
#######################################################################
# STARTING PROCEDURES
print("Bot loaded. Loading config and scores...")
try:
    loadconfig()
    print("Config loaded.")
except:
    print("Config not loaded! Check config file and reboot bot")
    Var.SWITCH = False

try:
    loadscores()
    print("Scores loaded.")
except:
    print("Scores not loaded! Check or delete 'userscores.txt' file and "
          "reboot bot")
    Var.SWITCH = False

if Var.SWITCH:
    try:
        s = socket.socket()
        s.connect((ChatVar.HOST, ChatVar.PORT))
        s.send(f"PASS {ChatVar.PASS}\r\n".encode("utf-8"))
        s.send(f"NICK {ChatVar.NICK}\r\n".encode("utf-8"))
        s.send(f"JOIN {ChatVar.CHAN}\r\n".encode("utf-8"))
        time.sleep(1)
        send_msg(Var.info_msg)
        s.setblocking(0)
    except:
        print("Connection failed. Check config settings and reload bot.")
        Var.SWITCH = False

def scanloop():
    try:
        response = s.recv(1024).decode("utf-8")
        if response == "PING :tmi.twitch.tv\r\n":
            s.send("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
            print("Pong sent")
            return
        username = re.search(r"\w+", response).group(0)
        if username == ChatVar.NICK:  # Ignore this bot's messages
            return
        message = ChatVar.CHAT_MSG.sub("", response)
        cleanmessage = re.sub(r"\s+", "", message, flags=re.UNICODE)
        print(f"USER RESPONSE: {username} : {message}")
        if cleanmessage in Var.COMMANDLIST:
            print("Command recognized.")
            trivia_commandswitch(cleanmessage, username)
            time.sleep(1)
        try:
            if fuzzy_match(2, message):
                print("Answer recognized.")
                trivia_answer(username)
            if fuzzy_match(3, message):
                print("Answer recognized.")
                trivia_answer(username)
        except:
            pass
    except:
        pass

# Infinite loop while bot is active to scan messages & perform routines
while Var.SWITCH:
    if Var.is_active:
        trivia_routinechecks()
    scanloop()
    time.sleep(1 / ChatVar.RATE)

# 0: Index
# 0: Game
# 1: Question
# 2: Answer
# 3: Answer 2
# 4: Grouping
# 5: Creator
