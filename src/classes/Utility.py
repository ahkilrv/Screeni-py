'''
 *  Project             :   Screenipy
 *  Author              :   Pranjal Joshi
 *  Created             :   28/04/2021
 *  Description         :   Class for managing misc and utility methods
'''

import os
import sys
import platform
import datetime
import pytz
import pickle
import requests
import time
import joblib
import pandas as pd
from alive_progress import alive_bar
from tabulate import tabulate
from time import sleep
from classes.ColorText import colorText
from classes.Changelog import VERSION, changelog
import classes.ConfigManager as ConfigManager

art = colorText.GREEN + '''
     .d8888b.                                             d8b                   
    d88P  Y88b                                            Y8P                   
    Y88b.                                                                       
     "Y888b.    .d8888b 888d888 .d88b.   .d88b.  88888b.  888 88888b.  888  888 
        "Y88b. d88P"    888P"  d8P  Y8b d8P  Y8b 888 "88b 888 888 "88b 888  888 
          "888 888      888    88888888 88888888 888  888 888 888  888 888  888 
    Y88b  d88P Y88b.    888    Y8b.     Y8b.     888  888 888 888 d88P Y88b 888 
     "Y8888P"   "Y8888P 888     "Y8888   "Y8888  888  888 888 88888P"   "Y88888 
                                                              888           888 
                                                              888      Y8b d88P 
                                                              888       "Y88P"  

''' + colorText.END

lastScreened = 'last_screened_results.pkl'
lastScreenedUnformatted = 'last_screened_unformatted_results.pkl'

# Class for managing misc and utility methods


class tools:

    def clearScreen():
        if platform.system() == 'Windows':
            os.system('cls')
        else:
            os.system('clear')
        print(art)

    # Print about developers and repository
    def showDevInfo():
        print('\n'+changelog)
        print(colorText.BOLD + colorText.WARN +
              "\n[+] Developer: Pranjal Joshi." + colorText.END)
        print(colorText.BOLD + colorText.WARN +
              ("[+] Version: %s" % VERSION) + colorText.END)
        print(colorText.BOLD +
              "[+] Home Page: https://github.com/pranjal-joshi/Screeni-py" + colorText.END)
        print(colorText.BOLD + colorText.FAIL +
              "[+] Read/Post Issues here: https://github.com/pranjal-joshi/Screeni-py/issues" + colorText.END)
        print(colorText.BOLD + colorText.GREEN +
              "[+] Join Community Discussions: https://github.com/pranjal-joshi/Screeni-py/discussions" + colorText.END)
        print(colorText.BOLD + colorText.BLUE +
              "[+] Download latest software from https://github.com/pranjal-joshi/Screeni-py/releases/latest" + colorText.END)
        input('')

    # Save last screened result to pickle file (primary: SQLite, backup: pickle)
    def setLastScreenedResults(df, unformatted=False):
        # Primary: save to SQLite
        try:
            from classes.Database import ScreeniDatabase
            db = ScreeniDatabase()
            criteria = 'last_screened_unformatted' if unformatted else 'last_screened'
            db.save_scan_results(criteria=criteria, index_name='last_screened', results_df=df)
        except Exception as e:
            pass  # SQLite failure is non-fatal
        # Backup: keep pickle
        try:
            if not unformatted:
                df.sort_values(by=['Stock'], ascending=True, inplace=True)
                df.to_pickle(lastScreened)
            else:
                df.sort_values(by=['Stock'], ascending=True, inplace=True)
                df.to_pickle(lastScreenedUnformatted)
        except IOError:
            print(colorText.BOLD + colorText.FAIL +
                  '[+] Failed to save recently screened result table on disk! Skipping..' + colorText.END)
            
    # Load last screened result from SQLite (primary) or pickle (fallback)
    def getLastScreenedResults():
        df = None
        # Primary: try SQLite
        try:
            from classes.Database import ScreeniDatabase
            db = ScreeniDatabase()
            df = db.get_last_scan_results(criteria='last_screened')
        except Exception:
            pass
        # Fallback: try pickle
        if df is None:
            try:
                df = pd.read_pickle(lastScreened)
            except FileNotFoundError:
                pass
        if df is not None:
            print(colorText.BOLD + colorText.GREEN +
                  '\n[+] Showing recently screened results..\n' + colorText.END)
            print(tabulate(df, headers='keys', tablefmt='psql'))
            print(colorText.BOLD + colorText.WARN +
                  "[+] Note: Trend calculation is based on number of recent days to screen as per your configuration." + colorText.END)
            input(colorText.BOLD + colorText.GREEN +
                  '[+] Press any key to continue..' + colorText.END)
        else:
            print(colorText.BOLD + colorText.FAIL +
                  '[+] Failed to load recently screened result table from disk! Skipping..' + colorText.END)

    def isTradingTime():
        curr = datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
        openTime = curr.replace(hour=9, minute=15)
        closeTime = curr.replace(hour=15, minute=30)
        return ((openTime <= curr <= closeTime) and (0 <= curr.weekday() <= 4))

    def isClosingHour():
        curr = datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
        openTime = curr.replace(hour=15, minute=00)
        closeTime = curr.replace(hour=15, minute=30)
        return ((openTime <= curr <= closeTime) and (0 <= curr.weekday() <= 4))

    def saveStockData(stockDict, configManager, loadCount):
        pass  # Deprecated: stock caching now uses Postgres via ScreeniDatabase

    def loadStockData(stockDict, configManager, proxyServer=None):
        pass  # Deprecated: stock caching now uses Postgres via ScreeniDatabase

    # Save screened results to excel
    def promptSaveResults(df):
        if isDocker() or isGui() or not sys.stdin.isatty():  # Skip export to excel inside docker or non-interactive
            return
        try:
            response = str(input(colorText.BOLD + colorText.WARN +
                                 '[>] Do you want to save the results in excel file? [Y/N]: ')).upper()
        except ValueError:
            response = 'Y'
        if response != 'N':
            filename = 'screenipy-result_' + \
                datetime.datetime.now().strftime("%d-%m-%y_%H.%M.%S")+".xlsx"
            df.to_excel(filename)
            print(colorText.BOLD + colorText.GREEN +
                  ("[+] Results saved to %s" % filename) + colorText.END)

    # Prompt for asking RSI
    def promptRSIValues():
        try:
            minRSI, maxRSI = int(input(colorText.BOLD + colorText.WARN + "\n[+] Enter Min RSI value: " + colorText.END)), int(
                input(colorText.BOLD + colorText.WARN + "[+] Enter Max RSI value: " + colorText.END))
            if (minRSI >= 0 and minRSI <= 100) and (maxRSI >= 0 and maxRSI <= 100) and (minRSI <= maxRSI):
                return (minRSI, maxRSI)
            raise ValueError
        except ValueError:
            return (0, 0)

    # Prompt for Reversal screening
    def promptReversalScreening():
        try:
            resp = int(input(colorText.BOLD + colorText.WARN + """\n[+] Select Option:
    1 > Screen for Buy Signal (Bullish Reversal)
    2 > Screen for Sell Signal (Bearish Reversal)
    3 > Screen for Momentum Gainers (Rising Bullish Momentum)
    4 > Screen for Reversal at Moving Average (Bullish Reversal)
    5 > Screen for Volume Spread Analysis (Bullish VSA Reversal)
    6 > Screen for Narrow Range (NRx) Reversal
    7 > Screen for Reversal using Lorentzian Classifier (Machine Learning based indicator)
    8 > Screen for Reversal using RSI MA Crossing
    0 > Cancel
[+] Select option: """ + colorText.END))
            if resp >= 0 and resp <= 8:
                if resp == 4:
                    try:
                        maLength = int(input(colorText.BOLD + colorText.WARN +
                                             '\n[+] Enter MA Length (E.g. 50 or 200): ' + colorText.END))
                        return resp, maLength
                    except ValueError:
                        print(colorText.BOLD + colorText.FAIL +
                              '\n[!] Invalid Input! MA Lenght should be single integer value!\n' + colorText.END)
                        raise ValueError
                elif resp == 6:
                    try:
                        maLength = int(input(colorText.BOLD + colorText.WARN +
                                             '\n[+] Enter NR timeframe [Integer Number] (E.g. 4, 7, etc.): ' + colorText.END))
                        return resp, maLength
                    except ValueError:
                        print(colorText.BOLD + colorText.FAIL + '\n[!] Invalid Input! NR timeframe should be single integer value!\n' + colorText.END)
                        raise ValueError
                elif resp == 7:
                    try:
                        return resp, 1
                    except ValueError:
                        print(colorText.BOLD + colorText.FAIL + '\n[!] Invalid Input! Select valid Signal Type!\n' + colorText.END)
                        raise ValueError
                elif resp == 8:
                    maLength = 9
                    return resp, maLength
                return resp, None
            raise ValueError
        except ValueError:
            return None, None

    # Prompt for Reversal screening
    def promptChartPatterns():
        try:
            resp = int(input(colorText.BOLD + colorText.WARN + """\n[+] Select Option:
    1 > Screen for Bullish Inside Bar (Flag) Pattern
    2 > Screen for Bearish Inside Bar (Flag) Pattern
    3 > Screen for the Confluence (50 & 200 MA/EMA)
    4 > Screen for VCP (Experimental)
    5 > Screen for Buying at Trendline (Ideal for Swing/Mid/Long term)
    0 > Cancel
[+] Select option: """ + colorText.END))
            if resp == 1 or resp == 2:
                candles = int(input(colorText.BOLD + colorText.WARN +
                                    "\n[+] How many candles (TimeFrame) to look back Inside Bar formation? : " + colorText.END))
                return (resp, candles)
            if resp == 3:
                percent = float(input(colorText.BOLD + colorText.WARN +
                                      "\n[+] Enter Percentage within which all MA/EMAs should be (Ideal: 1-2%)? : " + colorText.END))
                return (resp, percent/100.0)
            if resp >= 0 and resp <= 5:
                return resp, 0
            raise ValueError
        except ValueError:
            input(colorText.BOLD + colorText.FAIL +
                  "\n[+] Invalid Option Selected. Press Any Key to Continue..." + colorText.END)
            return (None, None)
        
    # Prompt for Similar stock search
    def promptSimilarStockSearch():
        try:
            stockCode = str(input(colorText.BOLD + colorText.WARN +
                                    "\n[+] Enter the Name of the stock to search similar stocks for: " + colorText.END)).upper()
            candles = int(input(colorText.BOLD + colorText.WARN +
                                    "\n[+] How many candles (TimeFrame) to look back for similarity? : " + colorText.END))
            return stockCode, candles
        except ValueError:
            input(colorText.BOLD + colorText.FAIL +
                "\n[+] Invalid Option Selected. Press Any Key to Continue..." + colorText.END)
            return None, None

    def getProgressbarStyle():
        bar = 'smooth'
        spinner = 'waves'
        if 'Windows' in platform.platform():
            bar = 'classic2'
            spinner = 'dots_waves'
        return bar, spinner



    def alertSound(beeps=3, delay=0.2):
        for i in range(beeps):
            print('\a')
            sleep(delay)

    def isBacktesting(backtestDate):
        try:
            if datetime.date.today() != backtestDate:
                return True
            return False
        except:
            return False
        
    def calculateBacktestReport(data, backtestDict:dict):
        try:
            recent = data.head(1)['Close'].iloc[0]
            for key, val in backtestDict.copy().items():
                if val is not None:
                    try:
                        backtestDict[key] = str(round((backtestDict[key]-recent)/recent*100,1)) + "%"
                    except TypeError:
                        del backtestDict[key]
                        # backtestDict[key] = None
                        continue
                else:
                    del backtestDict[key]
        except:
            pass
        return backtestDict

def isDocker():
    if 'SCREENIPY_DOCKER' in os.environ:
        return True
    return False

def isGui():
    if 'SCREENIPY_GUI' in os.environ:
        return True
    return False