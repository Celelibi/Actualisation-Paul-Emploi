#!/usr/bin/env python3

import argparse
import calendar
import configparser
import datetime
import email.message
import email.policy
import json
import locale
import logging
import mimetypes
import re
import smtplib
import traceback

import paul



smtphost = None
smtpport = None
smtpaccount = None
smtppassword = None



def sendmail(to, subj, msg, attachments=[]):
    # FIXME: use email.policy.SMTP when the bug #34424 is fixed
    policy = email.policy.EmailPolicy(raise_on_defect=True, linesep="\r\n", utf8=True)
    mail = email.message.EmailMessage(policy=policy)
    mail['Subject'] = "[BOT Paul Emploi] %s" % subj
    mail['From'] = "%s <%s>" % ("Auto-actualisation", smtpaccount)
    mail['To'] = "Chômeur <%s>" % to
    mail.set_content(msg, disposition='inline')

    for name, content in attachments:
        mime, encoding = mimetypes.guess_type(name)
        if mime is None or encoding is not None:
            mime = "application/octet-stream"

        maintype, subtype = mime.split("/")
        mail.add_attachment(content, maintype=maintype, subtype=subtype, filename=name)

    smtp = smtplib.SMTP_SSL(smtphost, port=smtpport)
    smtp.login(smtpaccount, smtppassword)
    smtp.send_message(mail)
    smtp.quit()



def make_answers(datestart, workfile=None):
    answers = paul.default_answers.copy()
    if workfile is None:
        logging.debug("No work file to parse")
        return answers

    datestart = datestart.date().replace(day=1)
    _, daysinmonth = calendar.monthrange(datestart.year, datestart.month)
    dateend = datestart + datetime.timedelta(days=daysinmonth)
    logging.info("Looking for work entries between %s and %s", datestart, dateend)

    parsere = re.compile(r'(\S+)\s+(\S+)\s+(\S+)')

    totalhours = 0
    totalrevenue = 0
    logging.info("Reading workfile: %s", workfile)

    with open(workfile) as fp:
        for line in fp:
            logging.debug("Reading workfile line: %r", line)
            line = line.split("#", 1)[0].rstrip()
            if not line:
                logging.debug("Ignoring empty line")
                continue

            match = parsere.match(line)
            if match is None:
                raise ValueError("Ill-formatted line in workfile: %r" % line)

            date = match.group(1)
            hours = match.group(2)
            rate = match.group(3)

            date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
            if date < datestart or date >= dateend:
                logging.debug("Date %s not in interval %s ... %s", date, datestart, dateend)
                continue

            hours = float(hours)
            rate = float(rate)
            revenue = hours * rate
            logging.debug("Adding %f hours and %f€ to the count", hours, revenue)

            totalhours += hours
            totalrevenue += revenue
            logging.debug("New total of %f hours and %f€", totalhours, totalrevenue)


    totalhours = int(totalhours)
    totalrevenue = int(totalrevenue)

    if totalhours == 0 and totalrevenue == 0:
        logging.debug("Work file show nothing for this month")
        return answers

    logging.info("Declaring %d hours for %d€", totalhours, totalrevenue)
    answers["travailleBloc"] = "OUI"
    answers["nbHeuresTravBloc"] = totalhours
    answers["montSalaireBloc"] = totalrevenue

    return answers



def dostuff(dest, user, password, workfile=None):
    pe = paul.PaulEmploi(user, password)

    situation = pe.situationsUtilisateur
    indemnisation = situation['indemnisation']
    actualisation = situation['actualisation']
    enddate = datetime.datetime.fromisoformat(indemnisation['dateDecheanceDroitAre'])
    indemndate = datetime.datetime.fromisoformat(actualisation['periodeCourante']['reference'])
    answers = make_answers(indemndate, workfile)
    actumsg, pdf = pe.actualisation(answers)

    dailyindemn = float(indemnisation['indemnisationJournalierNet'])
    _, daysinmonth = calendar.monthrange(indemndate.year, indemndate.month)
    indemnestimate = dailyindemn * daysinmonth

    msg = actumsg + "\n"
    msg += "Indemnisation prévue pour le mois de %s: %.2f€\n" % (indemndate.strftime("%B"), indemnestimate)
    msg += "Droit au chômage jusqu'au: %s\n" % enddate.strftime("%x")

    jsondump = json.dumps(situation, indent=8).encode("utf-8")
    att = [("situation.json", jsondump), ("declaration.pdf", pdf)]

    sendmail(dest, "Actualisation", msg, att)



def main():
    locale.setlocale(locale.LC_ALL, '')
    logfmt = "%(asctime)s %(levelname)s: %(message)s"
    logging.basicConfig(format=logfmt, level=logging.WARNING)

    parser = argparse.ArgumentParser(description="Bot d'actualisation pour Paul Emploi")
    parser.add_argument("cfgfile", metavar="configfile", help="Fichier de configuration")
    parser.add_argument("--user", "-u", metavar="PEusername", help="Compte Pôle Emploi configuré à utiliser")
    parser.add_argument("--work", "-w", metavar="worklog", help="Fichier des heures travaillées")
    parser.add_argument("--verbose", "-v", action="count", help="Augmente le niveau de verbosité")

    args = parser.parse_args()

    configpath = args.cfgfile
    peuser = args.user
    verbose = args.verbose
    workfile = args.work

    if verbose is not None:
        loglevels = ["WARNING", "INFO", "DEBUG", "NOTSET"]
        verbose = min(len(loglevels), verbose) - 1
        logging.getLogger().setLevel(loglevels[verbose])

    logging.info("Reading config file %s", configpath)
    config = configparser.ConfigParser()
    config.read(configpath)

    global smtphost, smtpport, smtpaccount, smtppassword
    smtphost = config["SMTP"]["smtphost"]
    smtpport = config["SMTP"].get("smtpport")
    smtpaccount = config["SMTP"]["smtpuser"]
    smtppassword = config["SMTP"]["smtppwd"]


    if peuser is None:
        section = next(s for s in config.sections() if s.startswith("Account."))
    else:
        section = "Account." + peuser

    logging.info("Using account section %s", section)
    peuser = config[section]["username"]
    pepwd = config[section]["password"]
    emailaddr = config[section]["email"]

    try:
        dostuff(emailaddr, peuser, pepwd, workfile)
    except:
        logging.exception("Top-level exception:")
        msg = "Exception caught while trying to run the \"actualisation\".\n\n"
        msg += traceback.format_exc()
        sendmail(smtpaccount, "Error", msg)





if __name__ == '__main__':
    main()
