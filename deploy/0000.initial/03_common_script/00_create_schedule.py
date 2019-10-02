from optparse import OptionParser
import json
from db.db_operation import MSOperation
from log.logger import Logger
import pyodbc
import requests
from pprint import pprint

parse = OptionParser()
parse.add_option("--retailer_key", action="store", dest="retailer_key")
parse.add_option("--vendor_key", action="store", dest="vendor_key")
parse.add_option("--meta", action="store", dest="meta")
(options, args) = parse.parse_args()

meta = json.loads(options.meta)
k8s_namespace = meta['k8s_namespace']

api_schedule_str = meta['api_schedule_str'] + '/schedule'
#api_schedule_str = 'http://qaz1k8mas001.rsicorp.local/common/schedule'
api_schedule_job_definitions = api_schedule_str + '/jobdefinitions'
api_schedule_job_schedules = api_schedule_str + '/schedules'

param_category = {
    "FastMovingProducts": {
        "switch_def": {
            "on": {"name":"calculateAA","value":"true","type":"bool"},
            "off": {"name":"calculateAA","value":"false","type":"bool"}
          },
          "switch": {
            "value": "on",
            "switchable": True
          },
          "basic": [
            {"name":"aaIndices","value":"LeagueScoreAvgVolume:1.0","type":"string"},
            {"name":"defaultDynamicHurdle","value":"2.8","type":"float"},
            {"name":"varianceOS","value":"1.59","type":"float"},
            {"name":"varianceSTO","value":"0.59","type":"float"},
            {"name":"daysforlsvfilter","value":"7","type":"int"},
            {"name":"aaRangingFeedType","value":"2","type":"int"}
          ],
          "advanced": [
            {"name":"aaBasePeriod","value":"26","type":"int"},
            {"name":"aaBasePeriodIDPLDPFix","value":"13","type":"int"},
            {"name":"aaDaysForLDP","value":"34","type":"int"},
            {"name":"aaIndexLimit","value":"50","type":"int"},
            {"name":"aaMinStoresPerLeague","value":"5","type":"int"},
            {"name":"aaSSHThreshold","value":"5","type":"int"},
            {"name":"calculateAAWeeklyData","value":"true","type":"bool"},
            {"name":"priceCalcMethod","value":"1","type":"int"},
            {"name":"fastProductThreshold","value":"0.8","type":"float"}
          ]
    },
    "General": {
      "switch_def": {
        "on": {},
        "off": {}
      },
      "switch": {
        "value": "on",
        "switchable": False
      },
      "basic": [
        {"name":"excludeGroupSales","value":"false","type":"bool"},
        {"name":"groupSalesThreshold","value":"20","type":"int"},
        {"name":"lowSIThreshold","value":"0.01","type":"float"},
        {"name":"shelfCapacityColumnName","value":"STORE SHELF CAPACITY VOLUME UNITS","type":"string"}
      ],
      "advanced": [
        {"name":"disableWeeklyFactDetection","value":"true","type":"bool"},
        {"name":"maxNumOfItemGroup","value":"50","type":"int"},
        {"name":"itemBatchSize","value":"20","type":"int"},
        {"name":"averageStoreCount","value":"0","type":"int"}
      ]
    },
    "Mid-SlowMovingProducts": {
      "switch_def": {
        "on": {"name":"calculateOSM","value":"true","type":"bool"},
        "off": {"name":"calculateOSM","value":"false","type":"bool"}
      },
      "switch": {
        "value": "on",
        "switchable": True
      },
      "basic": [
        {"name":"mixedMode","value":"false","type":"bool"},
        {"name":"siteGroupAttributes","value":"","type":"string"}
      ],
      "advanced": [
        {"name":"avgRSDemandPeriod","value":"28","type":"int"},
        {"name":"avgWaitDaysAfterGSLowerLimit","value":"2","type":"int"},
        {"name":"avgWaitDaysAfterGSUpperLimit","value":"7","type":"int"},
        {"name":"avgWaitDaysAfterOrdered","value":"3","type":"int"},
        {"name":"calculatedWaitDaysAfterGS","value":"true","type":"bool"},
        {"name":"dcOOSBackReadDays","value":"28","type":"int"},
        {"name":"distribution","value":"1","type":"int"},
        {"name":"gapProbability1","value":"0.02","type":"float"},
        {"name":"gapProbability2","value":"0.02","type":"float"},
        {"name":"incrementalBackReadDays","value":"98","type":"int"},
        {"name":"incrementallySalesRate","value":"true","type":"bool"},
        {"name":"maxAdjSearchDays","value":"0","type":"int"},
        {"name":"minAdjSearchDays","value":"0","type":"int"},
        {"name":"sameDayOrderReceipts","value":"false","type":"bool"},
        {"name":"stagingForLowVolumeSP","value":"true","type":"bool"},
        {"name":"staticRSDemand","value":"true","type":"bool"},
        {"name":"weeksForAverages","value":"8","type":"int"}
      ]
    },
    "OnhandExtrapolation": {
      "switch_def": {
        "on": {"name":"weeklyOnhand","value":"true","type":"bool"},
        "off": {"name":"weeklyOnhand","value":"false","type":"bool"}
      },
      "switch": {
        "value": "on",
        "switchable": True
      },
      "basic": [
        {"name":"onHandFillingMode","value":"1","type":"int"}
      ],
      "advanced": [
        {"name":"updateAdjForWeeklyOnHand","value":"true","type":"bool"}
      ]
    },
    "PhantomAnalysis": {
      "switch_def": {
        "on": {},
        "off": {}
      },
      "switch": {
        "value": "on",
        "switchable": False
      },
      "basic": [
        {"name":"numericPIErrLimit","value":"5","type":"int"}
      ],
      "advanced": [
        {"name":"calculatePI","value":"false","type":"bool"}
      ]
    },
    "POGSupport": {
      "switch_def": {
        "on": {"name":"enablePOGFilter","value":"true","type":"bool"},
        "off": {"name":"enablePOGFilter","value":"false","type":"bool"}
      },
      "switch": {
        "value": "on",
        "switchable": True
      },
      "basic": [
        {"name":"enableHistoricalPogFilter","value":"false","type":"bool"},
        {"name":"pogLagDays","value":"0","type":"int"},
        {"name":"pogWeekDays","value":"","type":"string"}
      ],
      "advanced": [
        {"name":"maxPogExtrapolateDays","value":"14","type":"int"}
      ]
    },
    "RetrospectiveMetrics": {
      "switch_def": {
        "on": {},
        "off": {}
      },
      "switch": {
        "value": "on",
        "switchable": False
      },
      "basic": [
        {"name":"writeBackWeeks","value":"0","type":"int"}
      ],
      "advanced": []
    },
    "DataComplete": {
      "switch_def": {
        "on": {},
        "off": {}
      },
      "switch": {
        "value": "on",
        "switchable": False
      },
      "basic": [
          {"name":"pos","value":"true","type":"bool"}, 
          {"name":"onHand","value":"true","type":"bool"},
          {"name":"itemCount","value":"true","type":"bool"},
          {"name":"storeCount","value":"true","type":"bool"},
          {"name":"feedback","value":"false","type":"bool"},
          {"name":"receipt","value":"false","type":"bool"},
          {"name":"pog","value":"false","type":"bool"}
      ],
     "advanced": [
          {"name":"paraDataCompleteETL","value":"eyJjaGVja09uIjpbInBvcyIsIm9uSGFuZCJdLCJtYXhQb2dFeHRyYXBvbGF0ZURheXMiOjE0LCJwb3MiOnsiZ3JlZW4iOltbMC44LDEuMl1dLCJ5ZWxsb3ciOltbMC4zLDAuOF0sWzEuMiwxLjddXSwicHJlV2VlayI6MTN9LCJpdGVtQ291bnQiOnsieWVsbG93IjpbMC44LDEuMl0sInByZVdlZWsiOjEzfSwic3RvcmVDb3VudCI6eyJ5ZWxsb3ciOlswLjgsMS4yXSwicHJlV2VlayI6MTN9LCJvbkhhbmQiOnsiZ3JlZW4iOltbMC44LDEuMl1dLCJ5ZWxsb3ciOltbMC4zLDAuOF0sWzEuMiwxLjddXSwicHJlV2VlayI6NH0sInBvZyI6eyJncmVlbiI6W1swLjgsMS4yXV0sInllbGxvdyI6W1swLjMsMC44XSxbMS4yLDEuN11dfSwicmVjZWlwdCI6eyJncmVlbiI6NSwieWVsbG93Ijo5fSwiZmVlZGJhY2siOnsiZ3JlZW4iOjUsInllbGxvdyI6OX0sInRpbWVfaW50ZXJ2YWxfdG9fZ28iOjJ9","type":"base64"}
      ]
    }
}

other_params = [
    {"name":"aaStagingOnly","value":"true","type":"bool"},
    {"name":"alertCode","value":"","type":"string"},
    {"name":"alertHistoryDays","value":"14","type":"int"},
    {"name":"asyncWrite","value":"8","type":"int"},
    {"name":"attrForConditionSavings","value":"","type":"string"},
    {"name":"auditSP","value":"false","type":"bool"},
    {"name":"bigPriceFallThreshold","value":"0.2","type":"float"},
    {"name":"bigPriceRiseThreshold","value":"0.2","type":"float"},
    {"name":"cacheSPD","value":"false","type":"bool"},
    {"name":"calculateCodeAge","value":"false","type":"bool"},
    {"name":"calculateDCOOS","value":"false","type":"bool"},
    {"name":"calculateExpectedLostDollars","value":"true","type":"bool"},
    {"name":"calculateLowExcessInv","value":"true","type":"bool"},
    {"name":"calculateNewAlert","value":"false","type":"bool"},
    {"name":"calculatePromoOOS","value":"true","type":"bool"},
    {"name":"calculateShelfVoid","value":"true","type":"bool"},
    {"name":"checkWHPKforPhantom","value":"false","type":"bool"},
    {"name":"dataCompletedThreshold","value":"0.01","type":"float"},
    {"name":"daysToLookBackWhenAssignItemKey","value":"28","type":"int"},
    {"name":"defaultTraitedValid","value":"true","type":"bool"},
    {"name":"demandExponentialMovingAverageAlpha","value":"0.5","type":""},
    {"name":"detectHolidays","value":"false","type":"bool"},
    {"name":"enabledSIBySPD","value":"true","type":"bool"},
    {"name":"enablePEMModule","value":"false","type":"bool"},
    {"name":"enablePostGenerate","value":"false","type":"bool"},
    {"name":"enableSPDFileWrite","value":"false","type":"bool"},
    {"name":"excessWks","value":"2","type":"int"},
    {"name":"fastSelling_VolumeLiftThreshold","value":"0.5","type":"float"},
    {"name":"fastSellingItems","value":"40","type":"int"},
    {"name":"forcedalert.enable","value":"true","type":""},
    {"name":"forceWriteback","value":"false","type":"bool"},
    {"name":"general_VolumeDropThreshold","value":"0.3","type":"float"},
    {"name":"general_VolumeLiftThreshold","value":"0.3","type":"float"},
    {"name":"genExternalAlerts","value":"false","type":"bool"},
    {"name":"genForceAlerts","value":"false","type":"bool"},
    {"name":"genForcedAlerts","value":"true","type":"bool"},
    {"name":"genNPIDVAlerts","value":"false","type":"bool"},
    {"name":"highVelocityThreshold","value":"5","type":"float"},
    {"name":"incremental","value":"false","type":"bool"},
    {"name":"invalidDropThreshold","value":"0.2","type":"float"},
    {"name":"isGoldenRatioRun","value":"true","type":"bool"},
    {"name":"lowSalesThreshold","value":"3","type":"int"},
    {"name":"mediumSelling_VolumeLiftPrefix","value":"2.7","type":"float"},
    {"name":"mediumSelling_VolumeLiftSuffix","value":"-0.49","type":"float"},
    {"name":"mediumSellingItems","value":"39","type":"int"},
    {"name":"min_valid_daily","value":"8","type":"int"},
    {"name":"minAlertNoRepeat","value":"7","type":"int"},
    {"name":"minAvgPosQtyExpected","value":"0.3","type":"float"},
    {"name":"minPres","value":"2","type":"int"},
    {"name":"Ods2F_DataTieOut","value":"0","type":"int"},
    {"name":"parallelDegree","value":"4","type":"int"},
    {"name":"persistSeasonality","value":"true","type":"bool"},
    {"name":"phantomLevel","value":"0.25","type":"float"},
    {"name":"posOnlyData","value":"false","type":"bool"},
    {"name":"possiblePhantomDays","value":"7","type":"int"},
    {"name":"postAFMProcessAlertMG","value":"false","type":"bool"},
    {"name":"priceFallThreshold","value":"0.08","type":"float"},
    {"name":"priceRiseThreshold","value":"0.08","type":"float"},
    {"name":"processOSMMeasureGroup","value":"true","type":"bool"},
    {"name":"prodCountToShrinkDBLog","value":"0","type":"int"},
    {"name":"realPriceDropWks","value":"8","type":"int"},
    {"name":"replenishHeuristicRT","value":"SameDayWhenSaleElseNextDay","type":"string"},
    {"name":"retroStartingInv","value":"false","type":"bool"},
    {"name":"rsdemandOnly","value":"false","type":"bool"},
    {"name":"runForecasting","value":"false","type":"bool"},
    {"name":"sendHighVelocityAlerts","value":"false","type":"bool"},
    {"name":"shelfOOSLowerLimit","value":"10","type":"int"},
    {"name":"shelfOOSUpperLimit","value":"25","type":"int"},
    {"name":"skipdetection","value":"false","type":"bool"},
    {"name":"slowSelling_VolumeLiftThreshold","value":"3","type":"float"},
    {"name":"slowSellingItems","value":"1","type":"int"},
    {"name":"spdDataDir","value":"","type":"string"},
    {"name":"splitSPD","value":"false","type":"bool"},
    {"name":"stagingOnly","value":"false","type":"bool"},
    {"name":"storeInvExcessFactor","value":"2","type":"float"},
    {"name":"storeInvLowFactor","value":"0.5","type":"float"},
    {"name":"storeInvMin","value":"3","type":"int"},
    {"name":"strictSalesRate","value":"false","type":"bool"},
    {"name":"useLogForPromoCalc","value":"false","type":"bool"},
    {"name":"useModeForAvgReplInterval","value":"true","type":"bool"},
    {"name":"useUPC4HVAlerts","value":"true","type":"bool"},
    {"name":"volumeDrop1","value":"0.5","type":"float"},
    {"name":"volumeDrop2","value":"0.55","type":"float"},
    {"name":"withRAAT","value":"false","type":"bool"},
    {"name":"writeConditions","value":"true","type":"bool"},
    {"name":"writePromoSPD","value":"false","type":"bool"},
    {"name":"writeSPD2","value":"false","type":"bool"},
    {"name":"backwardweeks","value":"52","type":"int"},
    {"name":"path", "value":"/osa/osacore", "type":"string"},
    {'name':'baselineIncrWeeks','type':'int','value':'8'},
    {'name':'substitutionFactorDefault','type':'float','value':'0.6'},
    {'name':'calculateDCOOSEpisodes','type':'bool','value':'false'},
    {'name':'codeLifeQUnits','type':'int','value':''},
    {'name':'maxShelfQtyGrossShipMultiplier','type':'int','value':'3'},
    {'name':'slowGapProbability','type':'float','value':'0.01'},
    {'name':'revDistCriteria','type':'bool','value':'false'},
    {'name':'confirmEpisodeCount','type':'int','value':'1'},
    {'name':'seasonalityAvgTotalSalesRandomnessThreshold','type':'float','value':'1'},
    {'name':'ghostLostUnitFactor','type':'float','value':'0.38'},
    {'name':'whpkTrimThreshold','type':'float','value':'0.1'},
    {'name':'velocityTierWeeks','type':'int','value':'8'},
    {'name':'useCalcEffectiveDate','type':'bool','value':'false'},
    {'name':'seasonalityMinThresholdStoreCount','type':'int','value':'0'},
    {'name':'jobBatchID','type':'int','value':'0'},
    {'name':'remappedReceiptsToGrossShip','type':'bool','value':'true'},
    {'name':'useRTFields','type':'bool','value':'true'},
    {'name':'safetyStockOveride','type':'bool','value':'false'},
    {'name':'shrinkBlockDays','type':'int','value':'14'},
    {'name':'minRetailerAdjSignificant','type':'int','value':'4'},
    {'name':'minContinuousGhostDays','type':'int','value':'3'},
    {'name':'profileTiming','type':'bool','value':'false'},
    {'name':'dVoidGapProbability','type':'float','value':'0.002'},
    {'name':'proportionSameDayDelivery','type':'float','value':'0.4'},
    {'name':'useGapCountsInT3PICommand','type':'bool','value':'true'},
    {'name':'resetEpisodes','type':'bool','value':'true'},
    {'name':'dcProtectedInterval','type':'int','value':'14'},
    {'name':'shrinkCountTail','type':'bool','value':'true'},
    {'name':'cacheRSDemand','type':'bool','value':'false'},
    {'name':'useLongestStretch','type':'bool','value':'false'},
    {'name':'dvoidLengthDefault','type':'float','value':'20'},
    {'name':'seasonalityMAMeanProportion','type':'float','value':'0.5'},
    {'name':'confirmMaxAllZ','type':'int','value':'3'},
    {'name':'pfpSet','type':'bool','value':'false'},
    {'name':'enableTwinTransfer','type':'bool','value':'false'},
    {'name':'rsretroOnly','type':'bool','value':'true'},
    {'name':'minDaysForDvoid','type':'int','value':'15'},
    {'name':'aaJava','type':'bool','value':'false'},
    {'name':'distributionVoidMinLength','type':'int','value':'61'},
    {'name':'endOfLifeSIThreshold2','type':'float','value':'0.02'},
    {'name':'sendLowVelocityAlerts','type':'bool','value':'false'},
    {'name':'minIntervalDaysPerSale','type':'int','value':'14'},
    {'name':'useSalesTrendForRSDemand','type':'bool','value':'false'},
    {'name':'forceAlertZeroSalesThreshhold','type':'int','value':'90'},
    {'name':'warmUpWeeks','type':'int','value':'4'},
    {'name':'shelfLengthDefault','type':'float','value':'3'},
    {'name':'endOfLifeSlopeThreshold','type':'float','value':'0'},
    {'name':'unexplainedSalesPatternPeriod','type':'int','value':'30'},
    {'name':'adjTailLength','type':'bool','value':'true'},
    {'name':'perfMonStagingTimeoutSeconds','type':'int','value':'7200'},
    {'name':'shrinkBlockReplenishmentCycles','type':'int','value':'5'},
    {'name':'useStoreClosureInfo','type':'bool','value':'true'},
    {'name':'whpkCalcMode','type':'int','value':'2'},
    {'name':'computeGapProbabilityBasedOnSalesGap','type':'bool','value':'true'},
    {'name':'distributionVoidPhantomMaxShelfThreshold','type':'float','value':'0.5'},
    {'name':'confirmShrinkEpisodeCount','type':'int','value':'2'},
    {'name':'seasonalityRandomnessTestThreshold','type':'float','value':'0.35'},
    {'name':'useAvgInventoryForGhost','type':'bool','value':'false'},
    {'name':'enableUnexplainedAdjAlert','type':'bool','value':'true'},
    {'name':'forecastErrorFactor','type':'float','value':'0.5'},
    {'name':'usePlanTable','type':'bool','value':'false'},
    {'name':'meanSalesThresholdForGapProbabilityBasedOnSalesGap','type':'float','value':'1'},
    {'name':'unexplainedSalesPatternMovingAverageDays','type':'int','value':'7'},
    {'name':'meanVarianceSalesRatioThresholdForPseudoInventory','type':'float','value':'1'},
    {'name':'defaultSPDFileDir','type':'string','value':''},
    {'name':'defaultSiteGroup','type':'string','value':''},
    {'name':'forceAlertZeroSalesThreshholdNewItem','type':'int','value':'60'},
    {'name':'writeDCOOSSPD','type':'bool','value':'false'},
    {'name':'calculateIZS','type':'bool','value':'false'},
    {'name':'salesType','type':'int','value':'0'},
    {'name':'writeWarmUpWeeks','type':'bool','value':'false'},
    {'name':'weeksOfDailyBaseline','type':'int','value':'2'},
    {'name':'updateAdjDays','type':'int','value':'3'},
    {'name':'payoutPortion','type':'float','value':'0.8'},
    {'name':'factorOfMinReceiptQtyForMinSafetyStock','type':'float','value':'1'},
    {'name':'ghostLengthDefault','type':'float','value':'70'},
    {'name':'confirmMinNoPIErrorDays','type':'int','value':'0'},
    {'name':'meanVarianceSalesRatioThresholdForGapProbability','type':'float','value':'1'},
    {'name':'endOfLifeDaysThreshold','type':'int','value':'21'},
    {'name':'deliveryDelayFromGS','type':'int','value':'2'},
    {'name':'productGap','type':'float','value':'0.02'},
    {'name':'adjPosPerUnexplained','type':'bool','value':'true'},
    {'name':'storeProtectedInterval','type':'int','value':'7'},
    {'name':'calculateRSBaseline','type':'bool','value':'true'},
    {'name':'demandMovingAverageDays','type':'int','value':'28'},
    {'name':'endOfLifeSIThreshold1','type':'float','value':'0.1'},
    {'name':'readSP','type':'bool','value':'false'},
    {'name':'dcReviewTime','type':'int','value':'3'},
    {'name':'shrinkBlockInactivePeriodInReplenishmentCycles','type':'int','value':'3'},
    {'name':'numericPIErrCorrectionLimit','type':'int','value':'2'},
    {'name':'codeLifeDaysSize','type':'int','value':'56'},
    {'name':'adjPOSTiming','type':'bool','value':'true'},
    {'name':'perfMonSampleIntervalSeconds','type':'int','value':'600'},
    {'name':'reportEpisodeOnLastDay','type':'bool','value':'false'},
    {'name':'writeSPDForLowVolumeSP','type':'bool','value':'false'},
    {'name':'newProductPosDays','type':'int','value':'60'},
    {'name':'simpleLostUnits','type':'bool','value':'true'},
    {'name':'issueShelfOOSAlerts','type':'bool','value':'true'}
]

param_list = []
for c in param_category:
    on_off = param_category[c]['switch']['value']
    if len(param_category[c]['switch_def'][on_off]):
        param_list += [param_category[c]['switch_def'][on_off]]
    param_list += param_category[c]['basic']
    param_list += param_category[c]['advanced']
param_list += other_params

#{"preWeek": 13, "checkOn": ["pos", "itemCount", "storeCount", "onHand"], "maxPogExtrapolateDays": 14, "pos": {"green": [[0.8, 1.2]], "yellow": [[0.3, 0.8], [1.2, 1.7]]}, "itemCount": {"yellow": [0.8, 1.2]}, "storeCount": {"yellow": [0.8, 1.2]}, "onHand": {"green": [[0.8, 1.2]], "yellow": [[0.3, 0.8], [1.2, 1.7]]}, "pog": {"green": [[0.8, 1.2]], "yellow": [[0.3, 0.8], [1.2, 1.7]]}, "receipt": {"green": 5, "yellow": 9}, "feedback": {"green": 5, "yellow": 9}}

defs = {
    "OSADataCompleteness": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Check data completeness for all vendors and retailers",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSADataCompleteness",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/dataCompleteETL/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }, 
        "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleExpression": "0 0/15 * * * ?",
            "scheduleType": "TIME", 
            "status": "ACTIVE"
        }
    }, 
    "OSAAFMCompleteness": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Check data completeness for AFM retailer rule",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSAAFMCompleteness",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/dataCompleteAG/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }, 
        "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleExpression": "0 0/5 * * * ?",
            "scheduleType": "TIME", 
            "status": "ACTIVE"
        }
    }, 
    "OSAFeedbackPersistency": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Persist feedback from Redis to Vertica",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSAFeedbackPersistency",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/persistfeedback/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }, "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleExpression": "0 0/10 * * * ?",
            "scheduleType": "TIME", 
            "status": "ACTIVE"
        }
    }, 
    "OSARetailerAFM": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Invoke AFM engine for retailer rules",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSARetailerAFM",
                        "ServiceURL": "http://afmservice.%s/osa/afm/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid", "value": "siloid", "type": "string"
                            }
                        ]
                    },
                    {
                        "StepID": "2",
                        "StepName": "Mobile Notification",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/mobilenotifier/"%k8s_namespace,
                        "DefaultSetting": [
                            {"name": "siloid", "value": "", "type": "string"}
                        ]
                    },
                    {
                        "StepID": "3",
                        "StepName": "Alert Delivery",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/dumper/"%k8s_namespace,
                        "DefaultSetting": [
                            {"name": "siloid", "value": "", "type": "string"}
                        ]
                    }
                ]
            }
        }
    }, 
    "OSASyncDimData": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Sync dim data from silo/hub to IRIS",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSASyncDimData",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/syncDimData/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }, "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleExpression": "0 0 8 * * ?",
            "scheduleType": "TIME", 
            "status": "ACTIVE"
        }
    }, 
    "OSASyncRDPFeedback": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Sync feedback from RDP to IRIS",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSASyncRDPFeedback",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/syncrdpfdbk/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }, "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleExpression": "0 0 20 * * ?",
            "scheduleType": "TIME", 
            "status": "ACTIVE"
        }
    }, 
    "OSMAlerting": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "OSM Analysis",
            "jobStepsJSON": {
                "JobSteps":[
                    {
                        "StepID": "1",
                        "StepName":"OSMStaging",
                        "ServiceURL":"amqp://osacoreservice.%s"%k8s_namespace,
                        "DefaultSetting":param_list
                    },
                    {
                        "StepID": "2",
                        "StepName":"Alert Generation",
                        "ServiceURL":"http://alertgeneration.%s/osa/ag/"%k8s_namespace,
                        "DefaultSetting":[
                            {"name":"hubid","value":"","type":"string"},
                            {"name":"siloid","value":"","type":"string"}
                        ]
                    }
                ]
            }
        }
    }, 
    "OSAScorecard": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Invoke scorecard",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSAScorecard",
                        "ServiceURL": "http://scorecard.%s/osa/scorecard/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }
    }, 
    "OSADeploy": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Invoke deploy",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSADeploy",
                        "ServiceURL": "http://deploy.%s/deploy/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }, "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleType": "EVENT", 
            "status": "ACTIVE"
        }
    },  
    "OSADataCleaning": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Cleanup data (aa/osm/raw alert/job history/temp tables)",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSADataCleaning",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/dataCleanup/"%k8s_namespace,
                        "DefaultSetting": [
                            {"name":"configJson","value":"[{'type': 'TABLE', 'excludeSchema': ['COMMON'], 'namePattern': ['AFM_RULES_FEEDBACK_STAGE_\\d+', 'FACT_PROCESSED_ALERT_SWAP_\\d+_\\d+', 'FACT_OSM_CONDITION_\\d+', 'FACT_OSM_STOREPRODUCT_\\d+', 'FACT_OSM_DC_PRODUCTDAY_\\d+', 'FACT_OSM_UNHSEASONALITY_PROFILE_\\d+', 'FACT_OSM_SP_AUDIT_\\d+', 'FACT_AA_STOREPRODUCT_\\d+', 'ANL_OSM_SITEGROUP_\\d+', 'ANL_OSM_DISABLESITE_\\d+', 'ANL_OSM_PRODUCT_ATTRIBUTE_\\d+', 'ANL_AA_RANGING_DATE_\\d+', 'ANL_OSM_DAILY_STORE_CNT_\\d+']},{'type': 'DATA', 'reserveDays': 14, 'excludeSchema': ['COMMON'], 'partitionTable': {'SEQ_NUM': ['FACT_RAW_ALERT', 'FACT_OSM_STOREPRODUCT', 'FACT_AA_STOREPRODUCT', 'FACT_OSM_CONDITION', 'FACT_OSM_UNHSEASONALITY_PROFILE', 'FACT_OSM_STORE', 'FACT_OSM_PRODUCT']}}]","type":"string"}
                        ]
                    }
                ]
            }
        }, "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleExpression": "0 0 10 * * ?",
            "scheduleType": "TIME",
            "status": "ACTIVE"
        }
    }, 
    "OSADumpDataToAzure": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Dump osm and aa spd data to Azure Blob Storage",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "DefaultSetting": [
                            {"type":"int","value":"20","name":"batchSize"},
                            {"type":"string", "value":"/osa/osacore/dumpdata", "name":"path"}
                        ],
                        "ServiceURL": "amqp://osacoreservice.%s"%k8s_namespace,
                        "StepName": "OSM Dump SPD Data"
                    }
                ]
            }
        }, "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleType": "EVENT",
            "status": "ACTIVE"
        }
    }, 
    "OSACoreProcess": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "OSM Analysis",
            "jobStepsJSON": {
                "JobSteps":[
                    {
                        "StepID": "1",
                        "StepName":"OSMStaging",
                        "ServiceURL":"amqp://osacoreservice.%s"%k8s_namespace,
                        "DefaultSetting":param_list
                    }
                ]
            }
        }
    },
    "OSADataCompletenessBlob": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Check if OSM SPD data is synced to Blob Storage for Retail Compass",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSABlobCompleteness",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/dataCompleteBlob/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        },
        "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleExpression": "0 0/15 * * * ?",
            "scheduleType": "TIME",
            "status": "ACTIVE"
        }
    },
    "OSAPacificNotification": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Send Kafka Message to Notify Pacific",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSAPacificNotification",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/pacificnotifier/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }, "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleType": "EVENT",
            "status": "ACTIVE"
        }
    },
    "OSADataCompletenessVR": {
        "definition": {
            "className": "com.rsi.schedule.job.BatchJobWrapper",
            "description": "Check data completeness for single vendor and retailer. Called by OSADataCompleteness",
            "jobStepsJSON": {
                "JobSteps": [
                    {
                        "StepID": "1",
                        "StepName": "OSADataCompletenessVR",
                        "ServiceURL": "http://osabundle.%s/osa_bundle/dataCompleteETLVR/"%k8s_namespace,
                        "DefaultSetting": [
                            {
                                "name": "siloid",
                                "value": "siloid",
                                "type": "string"
                            }
                        ]
                    }
                ]
            }
        }, "schedule": {
            "creater": "iris",
            "priority": 0,
            "repeatCount": 0,
            "repeatInterval": 0,
            "scheduleType": "EVENT",
            "status": "ACTIVE"
        }
    }
}

headers = {
    #"tokenid": "eyJhbGciOiJIUzI1NiJ9.eyJjb29raWVOYW1lIjoicnNpU3NvTmV4dEdlbiIsImNvb2tpZVZhbHVlIjoiQVFJQzV3TTJMWTRTZmN4ZVNqN1JSbmliUzNRNjg1YlpUelNGNTFWa0ZJX1Vkb2suKkFBSlRTUUFDTURFQUFsTkxBQk15TnpRMk5ETXpOREU1TkRnNU56UTRNalk1QUFKVE1RQUEqIiwic3RhdHVzIjoic3VjY2VzcyIsInVzZXJJZCI6ImhvbmcuaHVAcnNpY29ycC5sb2NhbCIsImlhdCI6MTU0MzIyMDg2MX0.9wkTfEO1LN-RiTmxtQDfIZl-0bfDVELC6oUKzCFHIak", 
    "content-type": "application/json"
}

if 'extra_args' in meta and meta['extra_args'] != None and len(meta['extra_args'])>0:
    try:
        extra_args_meta = json.loads(meta['extra_args'])
        if 'tokenid' in extra_args_meta:
            headers['tokenid'] = extra_args_meta['tokenid'] # this is only for testing on local, we need to pass --extra_args '{"tokenid":"xyz"}'
    except: 
        print('No tokenid is found in extra_args.')


def install_job_definition():
    r = requests.get(api_schedule_job_definitions, headers=headers)
    print('job definition url: %s'%api_schedule_job_definitions)
    print('return text: %s'%r.text)
    return_body = json.loads(r.text)
    existing_definitions = dict([(def_content['jobDefName'], def_content['id']) 
                                    for def_content in return_body 
                                    if def_content['jobDefName'] in defs
                                ]
                               )
    print(existing_definitions)

    for def_name in defs:
        body = defs[def_name]['definition']
        body['jobDefName'] = def_name
        if def_name in existing_definitions:
            body['id'] = existing_definitions[def_name]
            pprint(body)
            requests.put(api_schedule_job_definitions, data=json.dumps(body).replace('"type":"base64"', '"type":"string"'), headers=headers)
            print('jobDefName %s updated.'%def_name)
        else:
            pprint(body)
            requests.post(api_schedule_job_definitions, data=json.dumps(body).replace('"type":"base64"', '"type":"string"'), headers=headers)
            print('jobDefName %s created.'%def_name)
        
    
def install_schedule():
    r = requests.get(api_schedule_job_definitions, headers=headers)
    print('job definition url: %s'%api_schedule_job_definitions)
    print('return text: %s'%r.text)
    return_body = json.loads(r.text)
    existing_definitions = dict([(def_content['jobDefName'], def_content['id']) 
                                    for def_content in return_body 
                                    if def_content['jobDefName'] in defs
                                ]
                               )
    print(existing_definitions)
    
    for d in existing_definitions:
        if 'schedule' not in defs[d]:
            continue
        body = defs[d]['schedule']
        job_def_id = existing_definitions[d]
        body['groupName'] = '%s:singleton'%job_def_id
        body['jobDefinitionId'] = job_def_id
        body['scheduleName'] = '%s:singleton:%s'%(job_def_id, d)
        
        api_query_schedules = api_schedule_job_definitions + '/%s/schedules'%job_def_id
        r = requests.get(api_query_schedules, headers=headers)
        return_body = json.loads(r.text)
        
        if ('status' in return_body and return_body['status']==404) or len(return_body)==0:
            pprint(body)
            requests.post(api_schedule_job_schedules, data=json.dumps(body), headers=headers)
            print('schedule %s created.'%body['scheduleName'])
        else:
            schedule_id = return_body[0]['id'] # the job defs here only have one instance, so return_body[0]
            body['id'] = schedule_id
            pprint(body)
            requests.put(api_schedule_job_schedules, data=json.dumps(body), headers=headers)
            print('schedule %s updated.'%body['scheduleName'])


def insert_default_params():
    sql_handler = MSOperation(meta=meta)
    sql = "UPDATE META_DIM_DTL SET ATTR_TEXT = '%s' WHERE DEF_ID=(SELECT ID FROM META_DIM_DEF WHERE NAME='defaultParamCategory')"%json.dumps(param_category)
    try:
        sql_handler.execute(sql)
    finally:
        sql_handler.close_connection()
        
        
def main(): 
    print('>>>Start to create/update job definitions...')
    install_job_definition()
    
    print('>>>Start to create/update job schedules...')
    install_schedule()
    
    print('>>>Start to insert default parameter values...')          
    insert_default_params()
        
    print('>>>Done')
    
    
main()