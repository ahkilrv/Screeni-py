'''
 *  Project             :   Screenipy
 *  Author              :   Pranjal Joshi, Swar Patel
 *  Created             :   18/05/2021
 *  Description         :   Class for managing multiprocessing
'''

import multiprocessing
import gc
import pandas as pd
import numpy as np
import sys
import os
import pytz
import traceback
from queue import Empty
from datetime import datetime
import classes.Fetcher as Fetcher
import classes.Screener as Screener
import classes.Utility as Utility
from copy import deepcopy
from classes.CandlePatterns import CandlePatterns
from classes.ColorText import colorText
from classes.SuppressOutput import SuppressOutput
from classes.Database import ScreeniDatabase


def screen_one_stock(item, db, screenCounter, screenResultsCounter, proxyServer,
                     keyboardInterruptEvent, isTradingTime):
    tickerOption, executeOption, reversalOption, maLength, daysForLowestVolume, minRSI, maxRSI, respChartPattern, insideBarToLookback, totalSymbols, configManager, fetcher, screener, candlePatterns, stock, newlyListedOnly, downloadOnly, vectorSearch, isDevVersion, backtestDate = item
    screeningDictionary = {'Stock': "", 'Consolidating': "",  'Breaking-Out': "",
                           'MA-Signal': "", 'Volume': "", 'LTP': 0, 'RSI': 0, 'Trend': "", 'Pattern': ""}
    saveDictionary = {'Stock': "", 'Consolidating': "", 'Breaking-Out': "",
                      'MA-Signal': "", 'Volume': "", 'LTP': 0, 'RSI': 0, 'Trend': '', 'Pattern': ""}
    try:
        period = configManager.period
        if newlyListedOnly:
            if int(configManager.period[:-1]) > 250:
                period = '250d'
            else:
                period = configManager.period
        cached_data = db.get_cached_stock_data(stock)
        if (cached_data is None) or (configManager.cacheEnabled is False) or isTradingTime or downloadOnly:
            try:
                data, backtestReport = fetcher.fetchStockData(
                    stock, period, configManager.duration, proxyServer,
                    screenResultsCounter, screenCounter, totalSymbols,
                    backtestDate=backtestDate, tickerOption=tickerOption)
            except Exception:
                return screeningDictionary, saveDictionary, False
            if configManager.cacheEnabled and not isTradingTime:
                db.cache_stock_data(stock, data)
                if downloadOnly:
                    raise Screener.DownloadDataOnly
        else:
            data = cached_data
        fullData, processedData = screener.preprocessData(
            data, daysToLookback=configManager.daysToLookback)
        if type(vectorSearch) != bool and type(vectorSearch) and vectorSearch[2] == True:
            executeOption = 0
            screener.addVector(fullData, stock, vectorSearch[1])
        if newlyListedOnly:
            if not screener.validateNewlyListed(fullData, period):
                raise Screener.NotNewlyListed
        screenCounter.value += 1
        if not processedData.empty:
            urlStock = None
            if tickerOption == 16:
                urlStock = deepcopy(stock).replace('^', '').replace('.NS', '')
                stock = fetcher.getAllNiftyIndices()[stock]
            stock = stock.replace('^', '').replace('.NS', '')
            urlStock = stock.replace('&', '_') if urlStock is None else urlStock.replace('&', '_')
            screeningDictionary['Stock'] = colorText.BOLD + \
                colorText.BLUE + f'\x1B]8;;https://in.tradingview.com/chart?symbol=NSE%3A{urlStock}\x1B\\{stock}\x1B]8;;\x1B\\' + colorText.END if tickerOption < 15 \
                else colorText.BOLD + \
                colorText.BLUE + f'\x1B]8;;https://in.tradingview.com/chart?symbol={urlStock}\x1B\\{stock}\x1B]8;;\x1B\\' + colorText.END
            saveDictionary['Stock'] = stock
            consolidationValue = screener.validateConsolidation(
                processedData, screeningDictionary, saveDictionary, percentage=configManager.consolidationPercentage)
            isMaReversal = screener.validateMovingAverages(
                processedData, screeningDictionary, saveDictionary, maRange=1.25)
            isVolumeHigh = screener.validateVolume(
                processedData, screeningDictionary, saveDictionary, volumeRatio=configManager.volumeRatio)
            isBreaking = screener.findBreakout(
                processedData, screeningDictionary, saveDictionary, daysToLookback=configManager.daysToLookback)
            isLtpValid = screener.validateLTP(
                fullData, screeningDictionary, saveDictionary, minLTP=configManager.minLTP, maxLTP=configManager.maxLTP)
            if executeOption == 4:
                isLowestVolume = screener.validateLowestVolume(processedData, daysForLowestVolume)
            else:
                isLowestVolume = False
            isValidRsi = screener.validateRSI(
                processedData, screeningDictionary, saveDictionary, minRSI, maxRSI)
            try:
                with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                    currentTrend = screener.findTrend(
                        processedData, screeningDictionary, saveDictionary,
                        daysToLookback=configManager.daysToLookback, stockName=stock)
            except np.RankWarning:
                screeningDictionary['Trend'] = 'Unknown'
                saveDictionary['Trend'] = 'Unknown'
            with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                isCandlePattern = candlePatterns.findPattern(
                    processedData, screeningDictionary, saveDictionary)
            isConfluence = False
            isInsideBar = False
            isIpoBase = False
            if newlyListedOnly:
                isIpoBase = screener.validateIpoBase(stock, fullData, screeningDictionary, saveDictionary)
            if respChartPattern == 3 and executeOption == 7:
                isConfluence = screener.validateConfluence(
                    stock, processedData, screeningDictionary, saveDictionary, percentage=insideBarToLookback)
            else:
                isInsideBar = screener.validateInsideBar(
                    processedData, screeningDictionary, saveDictionary, chartPattern=respChartPattern, daysToLookback=insideBarToLookback)
            with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                if maLength is not None and executeOption == 6 and reversalOption == 6:
                    isNR = screener.validateNarrowRange(processedData, screeningDictionary, saveDictionary, nr=maLength)
                else:
                    isNR = screener.validateNarrowRange(processedData, screeningDictionary, saveDictionary)
            isMomentum = screener.validateMomentum(processedData, screeningDictionary, saveDictionary)
            isVSA = False
            if not (executeOption == 7 and respChartPattern < 3):
                isVSA = screener.validateVolumeSpreadAnalysis(processedData, screeningDictionary, saveDictionary)
            if maLength is not None and executeOption == 6 and reversalOption == 4:
                isMaSupport = screener.findReversalMA(fullData, screeningDictionary, saveDictionary, maLength)
            if executeOption == 6 and reversalOption == 8:
                isRsiReversal = screener.findRSICrossingMA(fullData, screeningDictionary, saveDictionary)
            isVCP = False
            if respChartPattern == 4:
                with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                    isVCP = screener.validateVCP(fullData, screeningDictionary, saveDictionary)
            isBuyingTrendline = False
            if executeOption == 7 and respChartPattern == 5:
                with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                    isBuyingTrendline = screener.findTrendlines(fullData, screeningDictionary, saveDictionary)
            try:
                backtestReport = Utility.tools.calculateBacktestReport(data=processedData, backtestDict=backtestReport)
                screeningDictionary.update(backtestReport)
                saveDictionary.update(backtestReport)
            except Exception:
                pass
            screenResultsCounter.value += 1
            if executeOption == 0:
                return screeningDictionary, saveDictionary, True
            if (executeOption == 1 or executeOption == 2) and isBreaking and isVolumeHigh and isLtpValid:
                return screeningDictionary, saveDictionary, True
            if (executeOption == 1 or executeOption == 3) and (consolidationValue <= configManager.consolidationPercentage and consolidationValue != 0) and isLtpValid:
                return screeningDictionary, saveDictionary, True
            if executeOption == 4 and isLtpValid and isLowestVolume:
                return screeningDictionary, saveDictionary, True
            if executeOption == 5 and isLtpValid and isValidRsi:
                return screeningDictionary, saveDictionary, True
            if executeOption == 6 and isLtpValid:
                if reversalOption == 1:
                    if saveDictionary['Pattern'] in CandlePatterns.reversalPatternsBullish or isMaReversal > 0 or 'buy' in saveDictionary['Pattern'].lower():
                        return screeningDictionary, saveDictionary, True
                elif reversalOption == 2:
                    if saveDictionary['Pattern'] in CandlePatterns.reversalPatternsBearish or isMaReversal < 0 or 'sell' in saveDictionary['Pattern'].lower():
                        return screeningDictionary, saveDictionary, True
                elif reversalOption == 3 and isMomentum:
                    return screeningDictionary, saveDictionary, True
                elif reversalOption == 4 and isMaSupport:
                    return screeningDictionary, saveDictionary, True
                elif reversalOption == 5 and isVSA and saveDictionary['Pattern'] in CandlePatterns.reversalPatternsBullish:
                    return screeningDictionary, saveDictionary, True
                elif reversalOption == 6 and isNR:
                    return screeningDictionary, saveDictionary, True
                elif reversalOption == 8 and isRsiReversal:
                    return screeningDictionary, saveDictionary, True
            if executeOption == 7 and isLtpValid:
                if respChartPattern < 3 and isInsideBar:
                    return screeningDictionary, saveDictionary, True
                if isConfluence:
                    return screeningDictionary, saveDictionary, True
                if isIpoBase and newlyListedOnly and not respChartPattern < 3:
                    return screeningDictionary, saveDictionary, True
                if isVCP:
                    return screeningDictionary, saveDictionary, True
                if isBuyingTrendline:
                    return screeningDictionary, saveDictionary, True
    except KeyboardInterrupt:
        pass
    except Fetcher.StockDataEmptyException:
        pass
    except Screener.NotNewlyListed:
        pass
    except Screener.DownloadDataOnly:
        pass
    except KeyError:
        pass
    except Exception as e:
        if isDevVersion:
            print("[!] Dev Traceback:")
            traceback.print_exc()
    return screeningDictionary, saveDictionary, False


class StockConsumer(multiprocessing.Process):

    def __init__(self, task_queue, result_queue, screenCounter, screenResultsCounter, db_dsn, proxyServer, keyboardInterruptEvent):
        multiprocessing.Process.__init__(self)
        self.multiprocessingForWindows()
        self.task_queue = task_queue
        self.result_queue = result_queue
        self.screenCounter = screenCounter
        self.screenResultsCounter = screenResultsCounter
        self.db_dsn = db_dsn
        self.db = None
        self.proxyServer = proxyServer
        self.keyboardInterruptEvent = keyboardInterruptEvent
        self.isTradingTime = Utility.tools.isTradingTime()

    def run(self):
        self.db = ScreeniDatabase(dsn=self.db_dsn)
        try:
            while not self.keyboardInterruptEvent.is_set():
                try:
                    next_task = self.task_queue.get()
                except Empty:
                    continue
                if next_task is None:
                    self.task_queue.task_done()
                    break
                answer = self.screenStocks(*(next_task))
                self.task_queue.task_done()
                self.result_queue.put(answer)
        except Exception as e:
            sys.exit(0)

    def screenStocks(self, tickerOption, executeOption, reversalOption, maLength, daysForLowestVolume, minRSI, maxRSI, respChartPattern, insideBarToLookback, totalSymbols,
                     configManager, fetcher, screener:Screener.tools, candlePatterns, stock, newlyListedOnly, downloadOnly, vectorSearch, isDevVersion, backtestDate, printCounter=False):
        screenResults = pd.DataFrame(columns=[
            'Stock', 'Consolidating', 'Breaking-Out', 'MA-Signal', 'Volume', 'LTP', 'RSI', 'Trend', 'Pattern'])
        screeningDictionary = {'Stock': "", 'Consolidating': "",  'Breaking-Out': "",
                               'MA-Signal': "", 'Volume': "", 'LTP': 0, 'RSI': 0, 'Trend': "", 'Pattern': ""}
        saveDictionary = {'Stock': "", 'Consolidating': "", 'Breaking-Out': "",
                          'MA-Signal': "", 'Volume': "", 'LTP': 0, 'RSI': 0, 'Trend': "", 'Pattern': ""}

        try:
            period = configManager.period

            if newlyListedOnly:
                if int(configManager.period[:-1]) > 250:
                    period = '250d'
                else:
                    period = configManager.period

            cached_data = self.db.get_cached_stock_data(stock)

            if (cached_data is None) or (configManager.cacheEnabled is False) or self.isTradingTime or downloadOnly:
                try:
                    data, backtestReport = fetcher.fetchStockData(stock,
                                                period,
                                                configManager.duration,
                                                self.proxyServer,
                                                self.screenResultsCounter,
                                                self.screenCounter,
                                                totalSymbols,
                                                backtestDate=backtestDate,
                                                tickerOption=tickerOption)
                except Exception as e:
                    return screeningDictionary, saveDictionary
                if configManager.cacheEnabled is True and not self.isTradingTime:
                    self.db.cache_stock_data(stock, data)
                    if downloadOnly:
                        raise Screener.DownloadDataOnly
            else:
                data = cached_data

                if printCounter:
                    try:
                        print(colorText.BOLD + colorText.GREEN + ("[%d%%] Screened %d, Found %d. Fetching data & Analyzing %s..." % (
                            int((self.screenCounter.value / totalSymbols) * 100), self.screenCounter.value, self.screenResultsCounter.value, stock)) + colorText.END, end='')
                        print(colorText.BOLD + colorText.GREEN + "=> Done!" +
                              colorText.END, end='\r', flush=True)
                    except ZeroDivisionError:
                        pass
                    sys.stdout.write("\r\033[K")

            fullData, processedData = screener.preprocessData(
                data, daysToLookback=configManager.daysToLookback)

            if type(vectorSearch) != bool and type(vectorSearch) and vectorSearch[2] == True:
                executeOption = 0
                with self.screenCounter.get_lock():
                    screener.addVector(fullData, stock, vectorSearch[1])

            if newlyListedOnly:
                if not screener.validateNewlyListed(fullData, period):
                    raise Screener.NotNewlyListed

            with self.screenCounter.get_lock():
                self.screenCounter.value += 1
            if not processedData.empty:
                urlStock = None
                if tickerOption == 16:
                    urlStock = deepcopy(stock).replace('^','').replace('.NS','')
                    stock = fetcher.getAllNiftyIndices()[stock]
                stock = stock.replace('^','').replace('.NS','')
                urlStock = stock.replace('&','_') if urlStock is None else urlStock.replace('&','_')
                screeningDictionary['Stock'] = colorText.BOLD + \
                    colorText.BLUE + f'\x1B]8;;https://in.tradingview.com/chart?symbol=NSE%3A{urlStock}\x1B\\{stock}\x1B]8;;\x1B\\' + colorText.END if tickerOption < 15 \
                    else colorText.BOLD + \
                    colorText.BLUE + f'\x1B]8;;https://in.tradingview.com/chart?symbol={urlStock}\x1B\\{stock}\x1B]8;;\x1B\\' + colorText.END
                saveDictionary['Stock'] = stock

                consolidationValue = screener.validateConsolidation(
                    processedData, screeningDictionary, saveDictionary, percentage=configManager.consolidationPercentage)
                isMaReversal = screener.validateMovingAverages(
                    processedData, screeningDictionary, saveDictionary, maRange=1.25)
                isVolumeHigh = screener.validateVolume(
                    processedData, screeningDictionary, saveDictionary, volumeRatio=configManager.volumeRatio)
                isBreaking = screener.findBreakout(
                    processedData, screeningDictionary, saveDictionary, daysToLookback=configManager.daysToLookback)
                isLtpValid = screener.validateLTP(
                    fullData, screeningDictionary, saveDictionary, minLTP=configManager.minLTP, maxLTP=configManager.maxLTP)
                if executeOption == 4:
                    isLowestVolume = screener.validateLowestVolume(processedData, daysForLowestVolume)
                else:
                    isLowestVolume = False
                isValidRsi = screener.validateRSI(
                    processedData, screeningDictionary, saveDictionary, minRSI, maxRSI)
                try:
                    with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                        currentTrend = screener.findTrend(
                            processedData,
                            screeningDictionary,
                            saveDictionary,
                            daysToLookback=configManager.daysToLookback,
                            stockName=stock)
                except np.RankWarning:
                    screeningDictionary['Trend'] = 'Unknown'
                    saveDictionary['Trend'] = 'Unknown'

                with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                    isCandlePattern = candlePatterns.findPattern(
                        processedData, screeningDictionary, saveDictionary)

                isConfluence = False
                isInsideBar = False
                isIpoBase = False
                if newlyListedOnly:
                    isIpoBase = screener.validateIpoBase(stock, fullData, screeningDictionary, saveDictionary)
                if respChartPattern == 3 and executeOption == 7:
                    isConfluence = screener.validateConfluence(stock, processedData, screeningDictionary, saveDictionary, percentage=insideBarToLookback)
                else:
                    isInsideBar = screener.validateInsideBar(processedData, screeningDictionary, saveDictionary, chartPattern=respChartPattern, daysToLookback=insideBarToLookback)

                with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                    if maLength is not None and executeOption == 6 and reversalOption == 6:
                        isNR = screener.validateNarrowRange(processedData, screeningDictionary, saveDictionary, nr=maLength)
                    else:
                        isNR = screener.validateNarrowRange(processedData, screeningDictionary, saveDictionary)

                isMomentum = screener.validateMomentum(processedData, screeningDictionary, saveDictionary)

                isVSA = False
                if not (executeOption == 7 and respChartPattern < 3):
                    isVSA = screener.validateVolumeSpreadAnalysis(processedData, screeningDictionary, saveDictionary)
                if maLength is not None and executeOption == 6 and reversalOption == 4:
                    isMaSupport = screener.findReversalMA(fullData, screeningDictionary, saveDictionary, maLength)
                if executeOption == 6 and reversalOption == 8:
                    isRsiReversal = screener.findRSICrossingMA(fullData, screeningDictionary, saveDictionary)

                isVCP = False
                if respChartPattern == 4:
                    with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                        isVCP = screener.validateVCP(fullData, screeningDictionary, saveDictionary)

                isBuyingTrendline = False
                if executeOption == 7 and respChartPattern == 5:
                    with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                        isBuyingTrendline = screener.findTrendlines(fullData, screeningDictionary, saveDictionary)

                try:
                    backtestReport = Utility.tools.calculateBacktestReport(data=processedData, backtestDict=backtestReport)
                    screeningDictionary.update(backtestReport)
                    saveDictionary.update(backtestReport)
                except:
                    pass

                with self.screenResultsCounter.get_lock():
                    if executeOption == 0:
                        self.screenResultsCounter.value += 1
                        return screeningDictionary, saveDictionary
                    if (executeOption == 1 or executeOption == 2) and isBreaking and isVolumeHigh and isLtpValid:
                        self.screenResultsCounter.value += 1
                        return screeningDictionary, saveDictionary
                    if (executeOption == 1 or executeOption == 3) and (consolidationValue <= configManager.consolidationPercentage and consolidationValue != 0) and isLtpValid:
                        self.screenResultsCounter.value += 1
                        return screeningDictionary, saveDictionary
                    if executeOption == 4 and isLtpValid and isLowestVolume:
                        self.screenResultsCounter.value += 1
                        return screeningDictionary, saveDictionary
                    if executeOption == 5 and isLtpValid and isValidRsi:
                        self.screenResultsCounter.value += 1
                        return screeningDictionary, saveDictionary
                    if executeOption == 6 and isLtpValid:
                        if reversalOption == 1:
                            if saveDictionary['Pattern'] in CandlePatterns.reversalPatternsBullish or isMaReversal > 0 or 'buy' in saveDictionary['Pattern'].lower():
                                self.screenResultsCounter.value += 1
                                return screeningDictionary, saveDictionary
                        elif reversalOption == 2:
                            if saveDictionary['Pattern'] in CandlePatterns.reversalPatternsBearish or isMaReversal < 0 or 'sell' in saveDictionary['Pattern'].lower():
                                self.screenResultsCounter.value += 1
                                return screeningDictionary, saveDictionary
                        elif reversalOption == 3 and isMomentum:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                        elif reversalOption == 4 and isMaSupport:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                        elif reversalOption == 5 and isVSA and saveDictionary['Pattern'] in CandlePatterns.reversalPatternsBullish:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                        elif reversalOption == 6 and isNR:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                        elif reversalOption == 8 and isRsiReversal:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                    if executeOption == 7 and isLtpValid:
                        if respChartPattern < 3 and isInsideBar:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                        if isConfluence:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                        if isIpoBase and newlyListedOnly and not respChartPattern < 3:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                        if isVCP:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
                        if isBuyingTrendline:
                            self.screenResultsCounter.value += 1
                            return screeningDictionary, saveDictionary
        except KeyboardInterrupt:
            pass
        except Fetcher.StockDataEmptyException:
            pass
        except Screener.NotNewlyListed:
            pass
        except Screener.DownloadDataOnly:
            pass
        except KeyError:
            pass
        except Exception as e:
            if isDevVersion:
                print("[!] Dev Traceback:")
                traceback.print_exc()
            if printCounter:
                print(colorText.FAIL +
                      ("\n[+] Exception Occured while Screening %s! Skipping this stock.." % stock) + colorText.END)
        return

    def multiprocessingForWindows(self):
        pass
