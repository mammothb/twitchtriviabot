# -*- coding: utf-8 -*-
"""
@author: cleartonic
"""

import collections
import configparser
import json
import logging
import time
import os
import os.path
import random
import re
import socket

import pandas as pd

from editdistance import DistanceAlgorithm, EditDistance

#######################################################################
# Global
#######################################################################
logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("TTB")
POS = ["1st", "2nd", "3rd"]

#######################################################################
# SETTINGS
#######################################################################
class Var:
    info_msg = "Twitch Trivia Bot loaded. Version 0.1.4."

    # SETTINGS FOR END USERS
    # Specify the filename (default "triviaset")
    filename = "triviaset"
    # Specify the file type. CSV (MUST be UTF-8), XLS, XLSX
    filetype = "csv"

    # Total questions to be answered for trivia round
    num_qs = None
    # Seconds to 1st hint after question is asked
    hint_time_1 = None
    # Seconds to 2nd hint after question is asked
    hint_time_2 = None
    # Seconds until the question is skipped automatically
    skiptime = None
    # Seconds to wait after previous question is answered before asking
    # next question
    delay = None
    admins = []

    # FUNCTION VARIABLES
    # open trivia source based on type
    if filetype == "csv":
        ts = pd.read_csv(f"{filename}.{filetype}")
    if filetype in ("xlsx", "xls"):
        ts = pd.read_excel(f"{filename}.{filetype}")
    if filetype not in ("xlsx", "xls", "csv"):
        LOG.warning("No file loaded. Type !stopbot and try loading again.")
    # Dynamic # of rows based on triviaset
    tsrows = ts.shape[0]
    # Set columns in quizset to same as triviaset
    qs = pd.DataFrame(columns=ts.columns)
    # Dictionary holding user scores, kept in '!' and loaded/created
    # upon trivia. [1,2,3] 1: Session score 2: Total trivia points
    # 3: Total wins
    userscores = {}
    COMMANDLIST = ["!triviastart", "!triviaend", "!triviatop3", "!score",
                   "!next", "!stop", "!loadconfig"]
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
    # Ongoing active timer
    TIMER = 0
    # Distance comparer
    comparer = None

    @classmethod
    def is_admin(cls, username):
        return username in cls.admins

    @classmethod
    def is_game_over(cls):
        return cls.num_qs == cls.q_no

    @classmethod
    def exceed_time(cls, timing):
        return cls.TIMER - cls.ask_time > timing

    @classmethod
    def q_category(cls):
        return cls.qs.iloc[cls.q_no, 0]

    @classmethod
    def q_question(cls):
        return cls.qs.iloc[cls.q_no, 1]

    @classmethod
    def q_answer(cls, offset):
        return cls.qs.iloc[cls.q_no, 2 + offset]

    @classmethod
    def user_session(cls, username):
        return Var.userscores[username][0]

    @classmethod
    def user_overall(cls, username):
        return Var.userscores[username][1]

    @classmethod
    def user_match(cls, username):
        return Var.userscores[username][2]

    @classmethod
    def user_add(cls, score_type, username, value):
        if score_type == "session":
            Var.userscores[username][0] += value
        elif score_type == "overall":
            Var.userscores[username][1] += value
        elif score_type == "match":
            Var.userscores[username][2] += value

# Variables for IRC / Twitch chat function
class ChatVar:
    HOST = None
    PORT = None
    NICK = None
    PASS = None
    CHAN = None
    # messages per second
    RATE = 120
    CHAT_MSG = re.compile(r"^:\w+!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :")

    @classmethod
    def is_bot(cls, username):
        return username.lower() == cls.NICK.lower()

#######################################################################
# Helper functions
#######################################################################
def fuzzy_match(offset, message):
    tol = 0.4 - 0.15 * Var.hint_req
    ans = Var.q_answer(offset)
    dist = Var.comparer.compare(ans.lower(), message.strip().lower(),
                                2 ** 31 - 1)
    closeness = dist / len(ans)
    LOG.info("Distance: %d | Difference: %f | Tolerance %f", dist, closeness,
             tol)
    return closeness < tol

def pluralize(count, singular, plural=None):
    if plural is not None:
        return f"{plural if count > 1 else singular}"
    else:
        return f"{singular}{'s' if count > 1 else ''}"

#######################################################################
# Backend code
#######################################################################
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

    Var.admins = config["Admin"]["admins"].split(",")

    ChatVar.HOST = config["Bot"]["HOST"]
    ChatVar.PORT = int(config["Bot"]["PORT"])
    ChatVar.NICK = config["Bot"]["NICK"]
    ChatVar.PASS = config["Bot"]["PASS"]
    ChatVar.CHAN = config["Bot"]["CHAN"]

def loadscores():
    if os.path.exists("userscores.txt"):
        with open("userscores.txt", "r") as fp:
            LOG.info("Score list loaded.")
            Var.userscores = json.load(fp)
    else:
        with open("userscores.txt", "w") as fp:
            LOG.info("No score list, creating...")
            Var.userscores = {"trivia_dummy": [0, 0, 0]}
            json.dump(Var.userscores, fp)

def dumpscores():
    try:
        with open("userscores.txt", "w") as fp:
            json.dump(Var.userscores, fp)
    except:
        LOG.error("Scores NOT saved!")

def build_session_quizset():
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
            LOG.war("Duplicate index. This should not happen, dropping row "
                    "from table. Please check config.txt's questions "
                    "are <= total # of questions in trivia set.")
            Var.ts.drop(Var.ts.index[[row_idx]])
    LOG.info("Quizset built.")

#######################################################################
# CODE
#######################################################################
# Trivia command switcher
def trivia_commandswitch(cleanmessage, username):
    # ADMIN ONLY COMMANDS
    if Var.is_admin(username):
        if cleanmessage == "!triviastart":
            if Var.is_active:
                LOG.info("Trivia already active.")
            else:
                trivia_start()
        elif cleanmessage == "!triviaend" and Var.is_active:
            trivia_end()
        elif cleanmessage == "!stop":
            stopbot()
        elif cleanmessage == "!loadconfig":
            loadconfig()
            send_msg("Config reloaded.")
        elif cleanmessage == "!next":
            trivia_skipquestion()

    # GLOBAL COMMANDS
    if cleanmessage == "!score":
        trivia_score(username)
    elif cleanmessage == "!triviatop3":
        topscore = trivia_top3overall()

        msg = "No scores yet."
        if topscore:
            msg = " ".join(f"{POS[i]} place: {score[0]} {score[1]} "
                           f"{pluralize(score[1], 'match', 'matches')} | "
                           f"{score[2]} {pluralize(score[2], 'point')}."
                           for i, score in enumerate(topscore))
        send_msg(msg)

# Trivia start build. ts = "Trivia set" means original master trivia
# file. qs = "Quiz set" means what's going to be played with for the
# session
def trivia_start():
    send_msg("Generating trivia questions for session...")
    trivia_clearscores()

    # Loop through TS and build QS until num_qs = trivia_numbers
    if Var.tsrows < Var.num_qs:
        Var.num_qs = Var.tsrows
        LOG.warning("Trivia questions for session exceeds trivia set's "
                    "population. Setting session equal to max questions.")
    build_session_quizset()
    Var.is_active = True
    Var.comparer = EditDistance(DistanceAlgorithm.DAMERUAUOSA)
    send_msg(f"Trivia has begun! Question Count: {Var.num_qs}. "
             f"Trivia will start in {Var.delay} seconds.")
    time.sleep(Var.delay)
    trivia_callquestion()

# Call trivia question
def trivia_callquestion():
    Var.question_asked = True
    Var.ask_time = round(time.time())

    q_no = Var.q_no + 1
    send_msg(f"Question {q_no}: [{Var.q_category()}] {Var.q_question()}")

    LOG.info("Question %d: %s | ANSWER: %s", q_no, Var.q_question(),
             Var.q_answer(0))

def trivia_answer(username):
    Var.question_asked = False
    try:
        Var.user_add("session", username, Var.ans_val)
        Var.user_add("overall", username, Var.ans_val)
    except:
        LOG.warning("Failed to find user! Adding new")
        # sets up new user
        Var.userscores[username] = [Var.ans_val, Var.ans_val, 0]
    # Save all current scores
    dumpscores()
    send_msg(f"{username} answers question #{Var.q_no + 1} "
             f"correctly! The answer is ** {Var.q_answer(0)} ** "
             f"{username} has {Var.user_session(username)} "
             f"{pluralize(Var.user_session(username), 'point')}!")
    time.sleep(Var.delay)
    Var.q_no += 1
    Var.hint_req = 0
    Var.question_asked = False
    Var.ask_time = 0

    if Var.is_game_over():
        trivia_end()
    else:
        LOG.info("Next question called...")
        trivia_callquestion()

# Finishes trivia by getting top 3 list, then adjusting final message
# based on how many participants. Then dumpscore()
def trivia_end():
    # Argument "1" will return the first in the list (0th position) for
    # list of top 3
    topscore = trivia_top3session()
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
    Var.qs = pd.DataFrame(columns=Var.ts.columns)

# after every time loop, routine checking of various vars/procs
def trivia_routinechecks():
    Var.TIMER = round(time.time())

    if Var.is_game_over():
        trivia_end()

    if Var.is_active and Var.question_asked:
        if Var.hint_req == 0 and Var.exceed_time(Var.hint_time_1):
            Var.hint_req = 1
            trivia_askhint(0)  # Ask first hint
        elif Var.hint_req == 1 and Var.exceed_time(Var.hint_time_2):
            Var.hint_req = 2
            trivia_askhint(1)  # Ask second hint
        elif Var.exceed_time(Var.skiptime):
            trivia_skipquestion()

# hinttype: 0 = 1st hint, 1 = 2nd hint
def trivia_askhint(hinttype=0):
    prehint = Var.q_answer(0)
    hint_no = hinttype + 1
    n = len(prehint)
    idx = random.sample(range(n), k=hint_no * n // 3)
    hint = "".join(c if i in idx or not c.isalnum() else "_"
                   for i, c in enumerate(prehint))
    send_msg(f"Hint #{hint_no}: {hint}")

def trivia_skipquestion():
    if Var.is_active:
        try:
            send_msg("Question was not answered in time. Answer: "
                     f"{Var.q_answer(0)}. Skipping to next question")
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

# Top 3 trivia (session)
def trivia_top3session():
    # temp dictionary just for keys & sessionscore
    scores = {i: Var.user_session(i)
              for i in Var.userscores if Var.user_session(i) > 0}
    score_counter = collections.Counter(scores)
    # top 3 list
    top3 = [[k, v] for k, v in score_counter.most_common(3)]
    return top3

# Top 3 trivia (overall)
def trivia_top3overall():
    scores = sorted(Var.userscores,
                    key=lambda x: (Var.user_match(x), Var.user_overall(x)),
                    reverse=True)
    top3 = [[k, Var.user_match(k), Var.user_overall(k)]
            for k in (scores[: 3] if len(scores) > 3 else scores)]
    return top3

# clears scores and assigns a win to winner
def trivia_clearscores():
    for i in Var.userscores:
        Var.userscores[i][0] = 0

# Add +1 to winner's win in userscores
def trivia_assignwinner(winner):
    Var.user_add("match", winner, 1)

def trivia_score(username):
    try:
        send_msg(
            "{} has {} points for this trivia session, {} total points and "
            "{} total wins.".format(username, *Var.userscores[username]))
    except KeyError:
        send_msg(f"{username} not found in database.")

# Chat message sender func
def send_msg(msg):
    s.send(":{0}!{0}@{0}.tmi.twitch.tv PRIVMSG {1} : {2}\r\n".format(
        ChatVar.NICK, ChatVar.CHAN, msg).encode("utf-8"))

# STOP BOT (sets loop to false)
def stopbot():
    Var.SWITCH = False

#######################################################################
# CHAT & BOT CONNECT
#######################################################################
def scanloop():
    try:
        response = s.recv(1024).decode("utf-8")
        if response == "PING :tmi.twitch.tv\r\n":
            s.send("PONG :tmi.twitch.tv\r\n".encode("utf-8"))
            LOG.info("Pong sent")
            return
        username = re.search(r"\w+", response).group(0)
        # if ChatVar.is_bot(username):  # Ignore this bot's messages
        #     return
        message = ChatVar.CHAT_MSG.sub("", response)
        cleanmessage = re.sub(r"\s+", "", message, flags=re.UNICODE)
        LOG.info("USER RESPONSE: %s : %s", username, message)
        if cleanmessage in Var.COMMANDLIST:
            LOG.info("Command recognized.")
            trivia_commandswitch(cleanmessage, username)
            time.sleep(1)
        else:
            try:
                if fuzzy_match(0, message):
                    LOG.info("Answer recognized.")
                    trivia_answer(username)
                if fuzzy_match(1, message):
                    LOG.info("Answer recognized.")
                    trivia_answer(username)
            except:
                pass
    except:
        pass

# STARTING PROCEDURES
LOG.info("Bot started. Loading config and scores...")
try:
    loadconfig()
    LOG.info("Config loaded.")
except (KeyError, ValueError):
    LOG.error("Config not loaded! Check config file and reboot bot")
    Var.SWITCH = False

try:
    loadscores()
except:
    LOG.error("Scores not loaded! Check / delete 'userscores.txt' file and "
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
        LOG.error("Connection failed. Check config settings and reload bot.")
        Var.SWITCH = False

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
