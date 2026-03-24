// SCADA GPU v5 — Static lookup tables and constants
// Extracted from legacy.js Phase 1

// Generator status texts (HGM9520N)
export const GENSET_ST_TEXT = {
  0: 'Ожидание', 1: 'Прогрев', 2: 'Подача топлива', 3: 'Стартер',
  4: 'Пауза стартера', 5: 'Пробный пуск', 6: 'Холостой ход', 7: 'Прогрев ВС',
  8: 'Ожид. нагрузки', 9: 'Работа', 10: 'Охлажд. ВС', 11: 'Холостой стоп',
  12: 'Аварийный стоп', 13: 'Ожид. остановки', 14: 'Ошибка останова'
};

// Switch status texts
export const SW_ST_TEXT = {
  0: 'Синхронизация', 1: 'Задерж. вкл.', 2: 'Ожид. замыкания', 3: 'Замкнут',
  4: 'Сброс нагрузки', 5: 'Задерж. откл.', 6: 'Ожид. размыкания', 7: 'Разомкнут'
};

// Mains status texts
export const MAINS_ST_TEXT = {
  0: 'Сеть норма', 1: 'Норма (задержка)', 2: 'Авария', 3: 'Авария (задержка)'
};
export const MAINS_ST_RU = {
  0: 'НОРМА', 1: 'НОРМА (задержка)', 2: 'АВАРИЯ', 3: 'АВАРИЯ (задержка)'
};

// ATS switch status texts (short)
export const ATS_ST_TEXT = {
  0: 'Синхр⟳', 1: 'Задерж.', 2: 'Ожид.вкл', 3: 'Замкнут',
  4: 'Сброс', 5: 'Задерж.', 6: 'Ожид.откл', 7: 'Откл.'
};

// Dashboard status styling
export const ST = {
  running: { dot: 'cd-g', bdg: 'bdg-run', txt: 'РАБОТА', cls: 's-run' },
  warning: { dot: 'cd-y', bdg: 'bdg-w', txt: 'ПРЕДУПР.', cls: 's-wrn' },
  alarm:   { dot: 'cd-r', bdg: 'bdg-a', txt: 'АВАРИЯ', cls: 's-alm' },
  standby: { dot: 'cd-x', bdg: 'bdg-off', txt: 'СТОП', cls: 's-stb' }
};

// Alarm register fields per device type
export const ALARM_FIELDS_GEN = [
  'alarm_sd_0','alarm_sd_1','alarm_sd_2','alarm_sd_3','alarm_sd_4','alarm_sd_5',
  'alarm_ts_0','alarm_ts_1','alarm_ts_2','alarm_ts_3','alarm_ts_4','alarm_ts_5',
  'alarm_tr_0','alarm_tr_1','alarm_tr_2','alarm_tr_3','alarm_tr_4','alarm_tr_5',
  'alarm_bk_0','alarm_bk_1','alarm_bk_2','alarm_bk_3','alarm_bk_4','alarm_bk_5',
  'alarm_wn_0','alarm_wn_1','alarm_wn_2','alarm_wn_3','alarm_wn_4','alarm_wn_5',
];
export const ALARM_FIELDS_ATS = [
  'alarm_reg_01','alarm_reg_02','alarm_reg_08',
  'alarm_reg_12','alarm_reg_14','alarm_reg_16',
  'alarm_reg_20','alarm_reg_21','alarm_reg_24',
  'alarm_reg_30','alarm_reg_44',
];

// HGM9520N alarm codes (protocol Table 27)
export const ALARM_CODES = {
  'E001':'Аварийный останов','E002':'Превышение оборотов','E003':'Снижение оборотов','E004':'Потеря сигнала скорости',
  'E005':'Повышенная частота генератора','E006':'Пониженная частота генератора','E007':'Повышенное напряжение генератора','E008':'Пониженное напряжение генератора',
  'E009':'Неудачный запуск','E010':'Перегрузка по току','E011':'Дисбаланс токов','E012':'Замыкание на землю',
  'E013':'Обратная мощность','E014':'Перегрузка по мощности','E015':'Потеря возбуждения','E016':'Ошибка связи с ЭБУ',
  'W001':'Авария ЭБУ','W002':'Вход высокой температуры','W003':'Вход низкого давления масла','W004':'Ошибка MSC ID',
  'W005':'Ошибка шины напряжения','W006':'Ошибка чередования фаз','W007':'Обрыв датчика температуры',
  'W008':'Высокая температура двигателя','W009':'Низкая температура двигателя','W010':'Обрыв датчика давления масла',
  'W011':'Высокое давление масла','W012':'Низкое давление масла','W013':'Низкий уровень топлива',
  'W014':'Ошибка зарядки','W015':'Повышенное напряжение АКБ','W016':'Пониженное напряжение АКБ',
  'W017':'Ошибка синхронизации','W018':'Регулятор оборотов на пределе','W019':'AVR на пределе',
  'W020':'Ошибка вкл. автомата сети','W021':'Ошибка вкл. автомата генератора','W022':'Требуется ТО',
  'M001':'Авария сети'
};

// AI provider configurations
export const AI_PROVIDERS = {
  openai:  { id:'openai',  name:'OpenAI', color:'#10a37f', icon:'🟢', models:['gpt-4o','gpt-4o-mini','gpt-4-turbo','o3-mini'], keyPrefix:'sk-', keyPlaceholder:'sk-proj-...' },
  claude:  { id:'claude',  name:'Claude', color:'#d97706', icon:'🟠', models:['claude-sonnet-4-20250514','claude-3-5-haiku-20241022','claude-opus-4-20250514'], keyPrefix:'sk-ant-', keyPlaceholder:'sk-ant-api03-...' },
  gemini:  { id:'gemini',  name:'Gemini', color:'#4285f4', icon:'🔵', models:['gemini-2.5-pro','gemini-2.5-flash','gemini-2.0-flash'], keyPrefix:'AI', keyPlaceholder:'AIza...' },
  grok:    { id:'grok',    name:'Grok',   color:'#ef4444', icon:'🔴', models:['grok-3','grok-3-mini','grok-2'], keyPrefix:'xai-', keyPlaceholder:'xai-...' }
};

// Event category labels and CSS classes
export const EVT_CAT_LABELS = {
  GEN_STATUS:'Статус', GEN_CRITICAL:'КРИТИЧ', MODE_CHANGE:'Режим',
  ATS_STATUS:'АВР', MAINS:'Сеть', OPERATOR:'Оператор', SYSTEM:'Связь', LOCAL:'UI'
};
export const EVT_CAT_CLS = {
  GEN_STATUS:'gs', GEN_CRITICAL:'crit', MODE_CHANGE:'mode',
  ATS_STATUS:'ats', MAINS:'mains', OPERATOR:'op', SYSTEM:'sys', LOCAL:'sys'
};

// Power chart colors and titles
export const PW_COLORS = { bus:'#00e09a', mains:'#4090ff', load:'#ffb020' };
export const PW_TITLES = { bus:'P генераторов', mains:'P сети', load:'P нагрузки' };

// Default TO template
export const DEF_TPL = {
  name: 'Стандартный',
  intervals: [
    { id:'to1', name:'ТО-1', hours:250, tasks:[{id:1,text:'Замена моторного масла',c:1},{id:2,text:'Замена масляного фильтра',c:1},{id:3,text:'Проверка уровня ОЖ',c:1},{id:4,text:'Проверка натяжения ремней',c:0},{id:5,text:'Проверка аккумулятора',c:0},{id:6,text:'Осмотр на утечки',c:0},{id:7,text:'Проверка показаний приборов',c:0}] },
    { id:'to2', name:'ТО-2', hours:500, tasks:[{id:1,text:'Замена моторного масла',c:1},{id:2,text:'Замена масляного фильтра',c:1},{id:3,text:'Проверка уровня ОЖ',c:1},{id:4,text:'Замена воздушного фильтра',c:1},{id:5,text:'Замена топливного фильтра',c:1},{id:6,text:'Проверка форсунок',c:0},{id:7,text:'Проверка давления масла',c:0},{id:8,text:'Слив отстоя из бака',c:0}] },
    { id:'to3', name:'ТО-3', hours:1000, tasks:[{id:1,text:'Замена моторного масла',c:1},{id:2,text:'Замена всех фильтров',c:1},{id:3,text:'Замена ОЖ полностью',c:1},{id:4,text:'Промывка системы охлаждения',c:1},{id:5,text:'Регулировка клапанных зазоров',c:1},{id:6,text:'Проверка компрессии',c:1},{id:7,text:'Проверка турбокомпрессора',c:0},{id:8,text:'Проверка генератора и стартера',c:0},{id:9,text:'Очистка радиатора',c:0}] },
    { id:'to4', name:'ТО-4', hours:2000, tasks:[{id:1,text:'Все работы ТО-3',c:1},{id:2,text:'Замена ремня ГРМ',c:1},{id:3,text:'Замена водяного насоса',c:1},{id:4,text:'Замена приводных ремней',c:1},{id:5,text:'Проверка опор двигателя',c:0},{id:6,text:'Диагностика ЭБУ',c:0},{id:7,text:'Проверка всех датчиков',c:0},{id:8,text:'Полный осмотр',c:1}] }
  ]
};

// Archive chart group definitions — Generator
export const ARC_GROUPS_GEN = {
  power: { fields:'power_total,power_a,power_b,power_c', labels:{power_total:'Общая мощность (кВт)',power_a:'Мощность фазы A (кВт)',power_b:'Мощность фазы B (кВт)',power_c:'Мощность фазы C (кВт)'}, unit:'кВт', colors:['#00e09a','#4090ff','#ffb020','#a070ff'],
    desc:'Активная мощность генератора. «Общая мощность» — суммарная нагрузка на генератор (P = Pa + Pb + Pc). Фазные значения A, B, C показывают распределение нагрузки по фазам. Перекос более 15% между фазами — ненормально.' },
  voltage: { fields:'gen_uab,gen_ubc,gen_uca,mains_uab', labels:{gen_uab:'Генератор UAB (линейное)',gen_ubc:'Генератор UBC (линейное)',gen_uca:'Генератор UCA (линейное)',mains_uab:'Напряжение сети UAB'}, unit:'В', colors:['#00e09a','#4090ff','#ffb020','#ff4060'],
    desc:'Линейные (межфазные) напряжения генератора и вводного напряжения сети. UAB — между фазами A и B, UBC — между B и C, UCA — между C и A. Норма 380-400В. Красная линия — напряжение внешней сети на вводе.' },
  engine: { fields:'engine_speed,coolant_temp,oil_pressure,oil_temp,gas_pressure,fuel_consumption,turbo_pressure,battery_volt', labels:{engine_speed:'Обороты двигателя (об/мин)',coolant_temp:'Температура ОЖ (°C)',oil_pressure:'Давление масла (кПа)',oil_temp:'Температура масла (°C)',gas_pressure:'Давление газа (кПа)',fuel_consumption:'Расход газа (м³/ч)',turbo_pressure:'Давление турбины (кПа)',battery_volt:'Напряжение АКБ (В)'}, unit:'', colors:['#00e09a','#ff4060','#ffb020','#f97316','#a070ff','#4090ff','#f472b6','#22d3ee'],
    desc:'Параметры двигателя генератора. Обороты: номинал 1500 об/мин. Температура ОЖ: норма 70-95°C, выше 100°C — перегрев. Давление масла: норма 200-500 кПа, падение ниже 100 — аварийное. АКБ: норма 24-28В (24В система). Давление газа: давление в рампе от ECU.' },
  current: { fields:'current_a,current_b,current_c,load_pct', labels:{current_a:'Ток генератора фаза A (А)',current_b:'Ток генератора фаза B (А)',current_c:'Ток генератора фаза C (А)',load_pct:'Нагрузка генератора (%)'}, unit:'А', colors:['#4090ff','#00e09a','#ffb020','#a070ff'],
    desc:'Токи на выходе генератора по трём фазам и процент нагрузки от номинала. Равномерное распределение токов по фазам — признак сбалансированной нагрузки. Нагрузка выше 80% длительно — повышенный износ.' },
  gas: { fields:'gas_pressure,air_gas_ratio,gas_temp,ignition_timing,exhaust_back_pressure,throttle_valve_pos,exhaust_oxygen,fuel_inlet_pressure', labels:{gas_pressure:'Давление газа (кПа)',air_gas_ratio:'Коэфф. воздух-газ λ',gas_temp:'Температура газа (°C)',ignition_timing:'Угол зажигания (°)',exhaust_back_pressure:'Противодавление выхлопа (кПа)',throttle_valve_pos:'Положение дросселя (%)',exhaust_oxygen:'Кислород в выхлопе (%)',fuel_inlet_pressure:'Давление на входе (кПа)'}, unit:'', colors:['#00e09a','#4090ff','#ff4060','#ffb020','#a070ff','#f472b6','#22d3ee','#f97316'],
    desc:'Параметры газовой системы ECU Exon-Gas. Давление газа: норма 5-30 кПа. λ (лямбда): оптимум 1.00-1.05 для метана, отклонение — проблемы смесеобразования. Угол зажигания: типично 15-25° до ВМТ. Температура газа: норма 10-40°C. Противодавление: рост = забитый катализатор/глушитель.' },
  efficiency: { fields:'fuel_consumption,power_total', labels:{fuel_consumption:'Расход газа (м³/ч)',power_total:'Мощность (кВт)'}, unit:'', colors:['#4090ff','#00e09a'],
    desc:'Удельный расход газа — отношение расхода газа (м³/ч) к вырабатываемой мощности (кВт). Показывает эффективность преобразования топлива в электроэнергию. Норма для газопоршневых ГПУ: 0.25-0.35 м³/кВт·ч. Рост удельного расхода = снижение КПД (износ свечей, разрегулировка, проблемы зажигания).',
    _computed:[{label:'Уд. расход газа (м³/кВт·ч)',color:'#f97316',calc:row=>{const fc=row.fuel_consumption!=null?Number(row.fuel_consumption):null;const pt=row.power_total!=null?Number(row.power_total):null;if(fc==null||pt==null||pt<5)return null;return fc/pt}}] }
};

// Archive chart group definitions — SPR (ATS)
export const ARC_GROUPS_SPR = {
  balance: { fields:'mains_total_p', _extraFetch:'multiset_total_p,busbar_p', labels:{mains_total_p:'P сети (кВт)'}, unit:'кВт', colors:['#4090ff'],
    desc:'Баланс мощности на объекте. <b>P генераторов</b> — суммарная мощность всех генераторов. <b>P сети</b> — мощность от внешней сети. P нагрузки = P генераторов + P сети.',
    _computed:[
      {label:'P генераторов (кВт)',color:'#00e09a',calc:row=>{const v=row.multiset_total_p!=null?Number(row.multiset_total_p):(row.busbar_p!=null?Number(row.busbar_p):null);return v}},
      {label:'P нагрузки (кВт)',color:'#ffb020',calc:row=>{const g=row.multiset_total_p!=null?Number(row.multiset_total_p):(row.busbar_p!=null?Number(row.busbar_p):0);const m=row.mains_total_p!=null?Number(row.mains_total_p):0;return g+m}}
    ] },
  power: { fields:'mains_total_p,mains_p_a,mains_p_b,mains_p_c', _extraFetch:'multiset_total_p,busbar_p', labels:{mains_total_p:'Σ P сети (кВт)',mains_p_a:'P сети ф.A (кВт)',mains_p_b:'P сети ф.B (кВт)',mains_p_c:'P сети ф.C (кВт)'}, unit:'кВт', colors:['#00e09a','#4090ff','#ffb020','#a070ff'],
    desc:'Активная мощность на вводе от внешней сети и суммарная мощность генераторов. <b>Σ P сети</b> = сумма трёх фаз ввода. <b>Σ P генераторов</b> — суммарная мощность генераторов.',
    _computed:[{label:'Σ P генераторов (кВт)',color:'#ff4060',calc:row=>{const v=row.multiset_total_p!=null?Number(row.multiset_total_p):(row.busbar_p!=null?Number(row.busbar_p):null);return v}}] },
  voltage: { fields:'mains_uab,mains_ubc,mains_uca,busbar_uab,busbar_ubc,busbar_uca', labels:{mains_uab:'Напряжение сети UAB (В)',mains_ubc:'Напряжение сети UBC (В)',mains_uca:'Напряжение сети UCA (В)',busbar_uab:'Напряжение шины UAB (В)',busbar_ubc:'Напряжение шины UBC (В)',busbar_uca:'Напряжение шины UCA (В)'}, unit:'В', colors:['#4090ff','#00e09a','#ffb020','#ff4060','#a070ff','#f472b6'],
    desc:'Линейные напряжения на вводе от внешней сети и на общей шине (после коммутации). Сеть — входящее напряжение от энергосбыта. Шина — напряжение, подаваемое потребителям. Норма 380-400В. Просадка шины при нагрузке — нормально до 5%.' },
  current: { fields:'mains_ia,mains_ib,mains_ic,busbar_current', labels:{mains_ia:'Ток ввода сети ф.A (А)',mains_ib:'Ток ввода сети ф.B (А)',mains_ic:'Ток ввода сети ф.C (А)',busbar_current:'Σ ток шины (А)'}, unit:'А', colors:['#4090ff','#00e09a','#ffb020','#ff4060'],
    desc:'Токи на <b>сетевом вводе</b> по фазам A/B/C и суммарный ток на общей шине. Пофазные токи — это измерения трансформаторов тока на вводе внешней сети. <b>Σ ток шины</b> — суммарное потребление всех нагрузок (пофазное разделение недоступно на HGM9560). Перекос токов ввода >15% — неравномерная нагрузка.' },
  frequency: { fields:'mains_freq,busbar_freq', labels:{mains_freq:'Частота внешней сети (Гц)',busbar_freq:'Частота на шине (Гц)'}, unit:'Гц', colors:['#4090ff','#ff4060'],
    desc:'Частота электрической сети на вводе и на общей шине. Номинал 50.0 Гц. Отклонение ±0.5 Гц — допустимо. Провалы частоты сети ниже 49 Гц указывают на перегрузку энергосистемы. При работе от генератора частота зависит от оборотов двигателя.' }
};

// Archive tab definitions
export const ARC_TABS_GEN = [
  {key:'power',label:'⚡ Мощность'},{key:'voltage',label:'🔌 Напряжение'},
  {key:'engine',label:'🛢 Двигатель'},{key:'gas',label:'🔥 Газ/ECU'},
  {key:'current',label:'〰 Токи'},{key:'efficiency',label:'⛽ Эффективность'}
];
export const ARC_TABS_SPR = [
  {key:'balance',label:'⚖ Баланс'},{key:'power',label:'⚡ Мощность'},
  {key:'voltage',label:'🔌 Напряжение'},{key:'current',label:'〰 Токи'},
  {key:'frequency',label:'📶 Частота'}
];
