// SCADA GPU v5.0 — Orchestrator (legacy.js)
// All code has been extracted into modules. This file imports them
// and wires window exports for HTML onclick/onchange handlers.

// === Foundation modules ===
import { $, esc, _v, _f1, _f2, R, RI, now, showM, hideM, fmtAlarmTime, fmtAlarmDuration } from './modules/utils.js';
import { toggleTheme, updateThemeBtn, getChartColors } from './modules/theme.js';
import {
  GENSET_ST_TEXT, SW_ST_TEXT, MAINS_ST_TEXT, MAINS_ST_RU, ATS_ST_TEXT, ST,
  ALARM_FIELDS_GEN, ALARM_FIELDS_ATS, ALARM_CODES, AI_PROVIDERS,
  EVT_CAT_LABELS, EVT_CAT_CLS, PW_COLORS, PW_TITLES, DEF_TPL,
  ARC_GROUPS_GEN, ARC_GROUPS_SPR, ARC_TABS_GEN, ARC_TABS_SPR
} from './modules/constants.js';

// === Shared state ===
import { G, sv, ae } from './modules/state.js';

// === API / WebSocket ===
import { api, API_BASE, WS_BASE, connectWebSocket, loadFromAPI, loadAlarmDefs, handleMetricsUpdate, decodeAlarms, trackAlarmTimes, getDeviceIdForSlot, getDeviceIdsForSite, getGenSlots } from './modules/api.js';

// === Feature modules ===
import { checkAuth, requestAuthCode, verifyAuthCode, showAuthTab, showEmailStep, showLoginTab, showUserProfile, applyRoleUI, doLogout, toggleMobileSidebar, loResend } from './modules/auth.js';

import { loadServerEvents, toggleEvPanel } from './modules/events.js';

import {
  renderDash, renderSB, genCard, sprCard, tog, stab, scrollToAlarm, openAlarms,
  applyGen, applyGenDetailed, applySpr, applySprDetailed, updateSprControlMode,
  updateSummary, showSummaryIssues, updateFlowFromMetrics, flowSvg,
  togDemo, demoTick,
  togSite, sel, selView, toggleEq, toggleAdmin,
  openAddSite, openEdit, openDel, saveSite, doDel, testConn,
  initApp
} from './modules/dashboard.js';

import {
  showArchive, arcTab, arcRange, arcDev, arcChGroup, arcLoadAlarms,
  arcSwitchSite, arcToggleField, arcRenderChart,
  dpToggle, dpNav, dpPickDay, dpApply, dpTimeChange,
  showPwChart, pwRange, openFieldArchive
} from './modules/archive.js';

import {
  showAlarms, almPeriod, almRefresh, almToggleRow, showAlarmSub,
  almAskSanek, almLoadHistory
} from './modules/alarms.js';

import './modules/alarm-modal.js';

import {
  renderTaskManager, showTaskTab, showTaskDetail, showCreateTaskForm, submitCreateTask,
  changeTaskStatus, loadTasks, _showCloseTaskForm, _submitCloseTask,
  openChecklist, showCreateRuleForm, submitCreateRule, renderRulesTab, toggleRule, updateTriggerConfig,
  renderCardsTab, showUploadCardForm, submitUploadCard,
  _mntShowCardDetail, _mntShowEquipDetail, _mntShowRecordForm, _mntSubmitRecord,
  _mntShowHoursForm, _mntSubmitHours, _mntResetEpoch, _mntToggleSort, _mntEqToggleSort,
  _mntOpenCardEditor, _mntLoadCards, _mntRenderEquipmentView,
  _mceConfirm, _mceSaveCardInfo, _mceAddIV, _mceSaveIV, _mceDelIV, _mceEditIV,
  _mceAddWI, _mceSaveWI, _mceEditWI, _mceDelWI,
  _mceAddSP, _mceSaveSP, _mceEditSP, _mceDelSP, _mceLinkEquip, _mceReparse,
  openTO, openTOTemplates, editTemplates, saveTemplates, completeTO,
  addTOInterval, delTOInterval, createBxTaskFromTO,
  getNextTO, getTpl, saveTpl, getTOData, saveTOData
} from './modules/tasks.js';

import {
  openSet, setTab, saveSet, cmdConfirm, applyPreset, updGenProtoLabel,
  initAIModal, selectAIProvider, activateAIProvider, testAIProvider, saveAIConfig, toggleAIKeyVis, applyAIResult,
  initBxModal, bxTab, testBxConnection, saveBxConfig, loadBxUsers, scanBxFolder, importBxFile,
  b24SaveMapping, b24TestTask, b24ForceSync, b24ToggleEq, stopB24Poll, showB24Dashboard,
  b24LoadStats, b24LoadTasks, kbDeleteDoc,
  onSprControlTabOpen, readSprConfig, saveSprConfig, setSprLoadMode,
  backupSprConfig, openRestoreBackup, restoreBackup, downloadBackup, deleteBackup, smartReset,
  openPowerLimitModal, closePowerLimitModal, savePowerLimit, plQuickP,
  renderAdminComms, loadAdminComms, renderAdminDecisions, loadAdminDecisions, renderAdminOfflineQueue,
  getBxUsers, getBxConfig, getAIConfig, updateQuickButtons
} from './modules/settings.js';

import {
  toggleSanek, sendToSanek, sanekHint, sanekNewSession, sanekConfirm,
  _snFeedback, _snLoadSession, _snSelectOption, _snShowHealthDetail,
  _snToggleHistory, _snUpdateThemeColors, _snDeleteSession, _snInitTypingDetection,
  _snUpdateCtxBadge, _snFormatText, _snToggleThinking
} from './modules/sanek.js';

import {
  showEconomics, econSetPeriod, econSwitchTab, econShowDetail,
  econCardInfo, econCmpDetail, econAddPrice, econDelPrice,
  econAddGridPrice, econDelGridPrice, econAddCategory, econDelCategory,
  econSavePlanned, econPlannedYearNav, econCopyYear, econPlannedMark
} from './modules/economics.js';

// === updateChartTheme (depends on G.arcChart / G.pwChart) ===
function updateChartTheme() {
  const c = getChartColors();
  if (G.arcChart) {
    G.arcChart.options.scales.x.grid.color = c.grid;
    G.arcChart.options.scales.x.border.color = c.border;
    G.arcChart.options.scales.x.ticks.color = c.tick;
    G.arcChart.options.scales.y.grid.color = c.grid;
    G.arcChart.options.scales.y.border.color = c.border;
    G.arcChart.options.scales.y.ticks.color = c.tick;
    G.arcChart.update('none');
  }
  if (G.pwChart) {
    G.pwChart.options.scales.x.grid.color = c.grid;
    G.pwChart.options.scales.x.border.color = c.border;
    G.pwChart.options.scales.x.ticks.color = c.tick;
    G.pwChart.options.scales.y.grid.color = c.grid;
    G.pwChart.options.scales.y.border.color = c.border;
    G.pwChart.options.scales.y.ticks.color = c.tick;
    G.pwChart.update('none');
  }
}
window._updateChartTheme = updateChartTheme;

// === Modal backdrop close ===
document.querySelectorAll('.mbg').forEach(m => m.addEventListener('click', e => { if (e.target === m) m.classList.remove('sh'); }));

// === Boot: check auth → init app ===
checkAuth().then(ok => { if (ok) initApp(); });

// ===== Window exports for onclick handlers =====
window.showM = showM;
window.hideM = hideM;
window.showAuthTab = showAuthTab;
window.requestAuthCode = requestAuthCode;
window.verifyAuthCode = verifyAuthCode;
window.showEmailStep = showEmailStep;
window.loResend = loResend;
window.toggleMobileSidebar = toggleMobileSidebar;
window.openAddSite = openAddSite;
window.renderTaskManager = renderTaskManager;
window.toggleAdmin = toggleAdmin;
window.showB24Dashboard = showB24Dashboard;
window.initAIModal = initAIModal;
window.renderAdminComms = renderAdminComms;
window.renderAdminDecisions = renderAdminDecisions;
window.renderAdminOfflineQueue = renderAdminOfflineQueue;
window.toggleTheme = toggleTheme;
window.toggleSanek = toggleSanek;
window.sendToSanek = sendToSanek;
window.sanekHint = sanekHint;
window.sanekNewSession = sanekNewSession;
window.sanekConfirm = sanekConfirm;
window.doLogout = doLogout;
window.togSite = togSite;
window.setTab = setTab;
window.stab = stab;
window.tog = tog;
window.togDemo = togDemo;
window.toggleEvPanel = toggleEvPanel;
window.openSet = openSet;
window.saveSet = saveSet;
window.saveSite = saveSite;
window.doDel = doDel;
window.testConn = testConn;
window.cmdConfirm = cmdConfirm;
window.arcTab = arcTab;
window.arcRange = arcRange;
window.arcDev = arcDev;
window.arcChGroup = arcChGroup;
window.arcLoadAlarms = arcLoadAlarms;
window.showPwChart = showPwChart;
window.pwRange = pwRange;
window.plQuickP = plQuickP;
window.almPeriod = almPeriod;
window.almRefresh = almRefresh;
window.almToggleRow = almToggleRow;
window.showAlarmSub = showAlarmSub;
window.scrollToAlarm = scrollToAlarm;
window.econSetPeriod = econSetPeriod;
window.econSwitchTab = econSwitchTab;
window.econShowDetail = econShowDetail;
window.econCardInfo = econCardInfo;
window.econCmpDetail = econCmpDetail;
window.econAddPrice = econAddPrice;
window.econDelPrice = econDelPrice;
window.econAddGridPrice = econAddGridPrice;
window.econDelGridPrice = econDelGridPrice;
window.econAddCategory = econAddCategory;
window.econDelCategory = econDelCategory;
window.econSavePlanned = econSavePlanned;
window.econPlannedYearNav = econPlannedYearNav;
window.econCopyYear = econCopyYear;
window.dpToggle = dpToggle;
window.dpNav = dpNav;
window.dpPickDay = dpPickDay;
window.dpApply = dpApply;
window.applyPreset = applyPreset;
window.kbDeleteDoc = kbDeleteDoc;
window.selectAIProvider = selectAIProvider;
window.activateAIProvider = activateAIProvider;
window.testAIProvider = testAIProvider;
window.saveAIConfig = saveAIConfig;
window.toggleAIKeyVis = toggleAIKeyVis;
window.applyAIResult = applyAIResult;
window.bxTab = bxTab;
window.testBxConnection = testBxConnection;
window.saveBxConfig = saveBxConfig;
window.loadBxUsers = loadBxUsers;
window.scanBxFolder = scanBxFolder;
window.importBxFile = importBxFile;
window.b24SaveMapping = b24SaveMapping;
window.b24TestTask = b24TestTask;
window.b24ForceSync = b24ForceSync;
window.b24ToggleEq = b24ToggleEq;
window.stopB24Poll = stopB24Poll;
window.initBxModal = initBxModal;
window.showSummaryIssues = showSummaryIssues;
window.loadAdminComms = loadAdminComms;
window.loadAdminDecisions = loadAdminDecisions;
window.showTaskDetail = showTaskDetail;
window.showTaskTab = showTaskTab;
window.showCreateTaskForm = showCreateTaskForm;
window.submitCreateTask = submitCreateTask;
window.changeTaskStatus = changeTaskStatus;
window.loadTasks = loadTasks;
window._showCloseTaskForm = _showCloseTaskForm;
window._submitCloseTask = _submitCloseTask;
window.openChecklist = openChecklist;
window.showCreateRuleForm = showCreateRuleForm;
window.submitCreateRule = submitCreateRule;
window.renderRulesTab = renderRulesTab;
window.toggleRule = toggleRule;
window.renderCardsTab = renderCardsTab;
window.showUploadCardForm = showUploadCardForm;
window.submitUploadCard = submitUploadCard;
window._mntShowCardDetail = _mntShowCardDetail;
window._mntShowEquipDetail = _mntShowEquipDetail;
window._mntShowRecordForm = _mntShowRecordForm;
window._mntSubmitRecord = _mntSubmitRecord;
window._mntShowHoursForm = _mntShowHoursForm;
window._mntSubmitHours = _mntSubmitHours;
window._mntResetEpoch = _mntResetEpoch;
window._mntToggleSort = _mntToggleSort;
window._mntEqToggleSort = _mntEqToggleSort;
window._mntOpenCardEditor = _mntOpenCardEditor;
window._mceConfirm = _mceConfirm;
window._mceSaveCardInfo = _mceSaveCardInfo;
window._mceAddIV = _mceAddIV;
window._mceSaveIV = _mceSaveIV;
window._mceAddWI = _mceAddWI;
window._mceSaveWI = _mceSaveWI;
window._mceEditWI = _mceEditWI;
window._mceDelWI = _mceDelWI;
window._mceAddSP = _mceAddSP;
window._mceSaveSP = _mceSaveSP;
window._mceEditSP = _mceEditSP;
window._mceDelSP = _mceDelSP;
window._mceLinkEquip = _mceLinkEquip;
window._mceReparse = _mceReparse;
window.openTO = openTO;
window.openTOTemplates = openTOTemplates;
window.editTemplates = editTemplates;
window.saveTemplates = saveTemplates;
window.completeTO = completeTO;
window.addTOInterval = addTOInterval;
window.delTOInterval = delTOInterval;
window.createBxTaskFromTO = createBxTaskFromTO;
window.openFieldArchive = openFieldArchive;
window.savePowerLimit = savePowerLimit;
window.closePowerLimitModal = closePowerLimitModal;
window.setSprLoadMode = setSprLoadMode;
window.saveSprConfig = saveSprConfig;
window.readSprConfig = readSprConfig;
window.backupSprConfig = backupSprConfig;
window.openRestoreBackup = openRestoreBackup;
window.restoreBackup = restoreBackup;
window.deleteBackup = deleteBackup;
window.downloadBackup = downloadBackup;
window._snFeedback = _snFeedback;
window._snLoadSession = _snLoadSession;
window._snSelectOption = _snSelectOption;
window._snShowHealthDetail = _snShowHealthDetail;
window._snToggleHistory = _snToggleHistory;
window._snToggleThinking = _snToggleThinking;
window._snUpdateThemeColors = _snUpdateThemeColors;
window.showUserProfile = showUserProfile;
window.selView = selView;
window.sel = sel;
window.renderDash = renderDash;
window.showAlarms = showAlarms;
window.openAlarms = openAlarms;
window.openEdit = openEdit;
window.openDel = openDel;
window.openPowerLimitModal = openPowerLimitModal;
window.toggleEq = toggleEq;
window.arcSwitchSite = arcSwitchSite;
window.arcToggleField = arcToggleField;
window.almAskSanek = almAskSanek;
window.almLoadHistory = almLoadHistory;
window.updGenProtoLabel = updGenProtoLabel;
window.updateTriggerConfig = updateTriggerConfig;
window.onSprControlTabOpen = onSprControlTabOpen;
window.smartReset = smartReset;
window.dpTimeChange = dpTimeChange;
window.econPlannedMark = econPlannedMark;
window.b24LoadStats = b24LoadStats;
window.b24LoadTasks = b24LoadTasks;
window._mceDelIV = _mceDelIV;
window._mceEditIV = _mceEditIV;
window._mntLoadCards = _mntLoadCards;
window._mntRenderEquipmentView = _mntRenderEquipmentView;
window._snDeleteSession = _snDeleteSession;
window.initApp = initApp;
window.showEconomics = showEconomics;
window.getNextTO = getNextTO;
window.getTpl = getTpl;
window.saveTpl = saveTpl;
window.getTOData = getTOData;
window.saveTOData = saveTOData;
window.getBxUsers = getBxUsers;
window.getBxConfig = getBxConfig;
window.getAIConfig = getAIConfig;
window.updateQuickButtons = updateQuickButtons;
window._snUpdateCtxBadge = _snUpdateCtxBadge;
window._snFormatText = _snFormatText;
window.showArchive = showArchive;
window.loadServerEvents = loadServerEvents;
window.getDeviceIdForSlot = getDeviceIdForSlot;
window.getGenSlots = getGenSlots;
window.getDeviceIdsForSite = getDeviceIdsForSite;
