export type Locale = "en" | "zh";

export interface Translations {
  // ── Common ──
  common: {
    save: string;
    saving: string;
    cancel: string;
    close: string;
    confirm: string;
    delete: string;
    refresh: string;
    retry: string;
    search: string;
    loading: string;
    create: string;
    creating: string;
    set: string;
    replace: string;
    clear: string;
    live: string;
    off: string;
    enabled: string;
    disabled: string;
    active: string;
    inactive: string;
    unknown: string;
    untitled: string;
    none: string;
    form: string;
    noResults: string;
    of: string;
    page: string;
    msgs: string;
    tools: string;
    match: string;
    other: string;
    configured: string;
    removed: string;
    failedToToggle: string;
    failedToRemove: string;
    failedToReveal: string;
    collapse: string;
    expand: string;
    general: string;
    messaging: string;
    pluginLoadFailed: string;
    pluginNotRegistered: string;
  };

  // ── App shell ──
  app: {
    brand: string;
    brandShort: string;
    closeNavigation: string;
    closeModelTools: string;
    footer: {
      org: string;
    };
    activeSessionsLabel: string;
    gatewayStatusLabel: string;
    /** Sidebar tooltip — messaging gateway is optional for dashboard Chat/TUI */
    messagingGatewayHint: string;
    gatewayStrip: {
      failed: string;
      off: string;
      running: string;
      starting: string;
      stopped: string;
    };
    nav: {
      analytics: string;
      chat: string;
      config: string;
      cron: string;
      knowledge: string;
      documentation: string;
      keys: string;
      logs: string;
      models: string;
      profiles: string;
      plugins: string;
      sessions: string;
      skills: string;
    };
    modelToolsSheetSubtitle: string;
    modelToolsSheetTitle: string;
    navigation: string;
    openDocumentation: string;
    openNavigation: string;
    pluginNavSection: string;
    sessionsActiveCount: string;
    statusOverview: string;
    system: string;
    webUi: string;
  };

  // ── Status page ──
  status: {
    actionFailed: string;
    actionFinished: string;
    actions: string;
    agent: string;
    connected: string;
    connectedPlatforms: string;
    disconnected: string;
    error: string;
    failed: string;
    gateway: string;
    gatewayFailedToStart: string;
    lastUpdate: string;
    noneRunning: string;
    notRunning: string;
    pid: string;
    platformDisconnected: string;
    platformError: string;
    activeSessions: string;
    recentSessions: string;
    restartGateway: string;
    restartingGateway: string;
    running: string;
    runningRemote: string;
    startFailed: string;
    starting: string;
    startedInBackground: string;
    stopped: string;
    updateHermes: string;
    updatingHermes: string;
    waitingForOutput: string;
  };

  // ── Sessions page ──
  sessions: {
    title: string;
    searchPlaceholder: string;
    noSessions: string;
    noMatch: string;
    startConversation: string;
    noMessages: string;
    untitledSession: string;
    deleteSession: string;
    confirmDeleteTitle: string;
    confirmDeleteMessage: string;
    sessionDeleted: string;
    failedToDelete: string;
    resumeInChat: string;
    /** Shown on /chat when ?resume= is present — model may differ from Models page default */
    chatResumeModelHint: string;
    /** CTA: navigate to /chat without resume to use current default model */
    chatStartFresh: string;
    /** Primary CTA to open the embedded Chat tab */
    openChat: string;
    /** Shown when embedded PTY chat is not enabled on this dashboard */
    chatDisabledHint: string;
    previousPage: string;
    nextPage: string;
    roles: {
      user: string;
      assistant: string;
      system: string;
      tool: string;
    };
  };

  // ── Analytics page ──
  analytics: {
    period: string;
    totalTokens: string;
    totalSessions: string;
    apiCalls: string;
    dailyTokenUsage: string;
    dailyBreakdown: string;
    perModelBreakdown: string;
    topSkills: string;
    skill: string;
    loads: string;
    edits: string;
    lastUsed: string;
    input: string;
    output: string;
    total: string;
    noUsageData: string;
    startSession: string;
    date: string;
    model: string;
    tokens: string;
    perDayAvg: string;
    acrossModels: string;
    inOut: string;
  };

  // ── Models page ──
  models: {
    modelsUsed: string;
    estimatedCost: string;
    tokens: string;
    sessions: string;
    avgPerSession: string;
    apiCalls: string;
    toolCalls: string;
    noModelsData: string;
    startSession: string;
  };

  // ── Logs page ──
  logs: {
    title: string;
    autoRefresh: string;
    file: string;
    level: string;
    component: string;
    lines: string;
    noLogLines: string;
  };

  // ── Cron page ──
  cron: {
    confirmDeleteMessage: string;
    confirmDeleteTitle: string;
    newJob: string;
    nameOptional: string;
    namePlaceholder: string;
    prompt: string;
    promptPlaceholder: string;
    schedule: string;
    schedulePlaceholder: string;
    deliverTo: string;
    scheduledJobs: string;
    noJobs: string;
    last: string;
    next: string;
    pause: string;
    resume: string;
    triggerNow: string;
    delivery: {
      local: string;
      telegram: string;
      discord: string;
      slack: string;
      email: string;
    };
  };

  // ── Knowledge bases page ──
  knowledgePage: {
    title: string;
    subtitle: string;
    newBase: string;
    nameLabel: string;
    namePlaceholder: string;
    modeLabel: string;
    modeVector: string;
    modeGraphrag: string;
    listHeading: string;
    empty: string;
    uploadFile: string;
    uploadHint: string;
    agentSummaryLabel: string;
    agentSummaryHint: string;
    agentSummaryPlaceholder: string;
    agentSummarySave: string;
    agentSummarySaved: string;
    routingSummaryReadonly: string;
    routingSummaryEmpty: string;
    summaryRoutingModeLabel: string;
    summaryRoutingManual: string;
    summaryRoutingAuto: string;
    summaryRoutingHintCreate: string;
    summaryDialogTitle: string;
    summarySettingsButton: string;
    summaryModeSaved: string;
    routingSummaryHiddenManual: string;
    routingSummaryAutoNote: string;
    agentSummaryNewLabel: string;
    agentSummaryNewHint: string;
    reindex: string;
    indexBuild: string;
    reuploadFile: string;
    backgroundRun: string;
    expandPanel: string;
    queryProgressTitle: string;
    queryRunning: string;
    queryCancelled: string;
    queryButtonAgain: string;
    confirmDeleteTitle: string;
    confirmDeleteMessage: string;
    statusIdle: string;
    statusIndexing: string;
    statusReady: string;
    statusError: string;
    created: string;
    uploadOk: string;
    uploadProgressTitle: string;
    uploadProgressHint: string;
    uploadElapsed: string;
    uploadPhaseStarting: string;
    uploadPhaseSaved: string;
    uploadPhaseWorking: string;
    uploadPhaseSkipMineruDisabled: string;
    uploadPhaseSkipMineruNoRoot: string;
    uploadPhaseSkipMineruBadRoot: string;
    uploadPhaseSkipNonPdf: string;
    uploadPhaseReadError: string;
    uploadPhaseMineruPrepare: string;
    uploadPhaseMineruParsing: string;
    uploadPhaseMineruParseDone: string;
    uploadPhaseMineruWriting: string;
    uploadPhaseMineruComplete: string;
    uploadPhaseMineruImportFailed: string;
    uploadPhaseMineruMissingMd: string;
    uploadPhaseMineruError: string;
    uploadPhaseUnknown: string;
    reindexNotImplemented: string;
    nameRequired: string;
    toolsCard: string;
    embedTestLabel: string;
    embedTestButton: string;
    embedTestResult: string;
    queryLabel: string;
    queryPlaceholder: string;
    queryButton: string;
    queryPickBase: string;
    queryKbKindChunk: string;
    queryKbKindGraphrag: string;
    queryGraphragMethodLabel: string;
    graphragMethodLocal: string;
    graphragMethodGlobal: string;
    graphragMethodBasic: string;
    reindexedChunks: string;
    reindexProgressTitle: string;
    reindexProgressTitleGraphrag: string;
    reindexProgressHint: string;
    reindexGraphragHint: string;
    reindexPhaseStarting: string;
    reindexWorking: string;
    reindexPhaseChunking: string;
    reindexPhaseChunkingPrep: string;
    reindexPhaseChunkingDetail: string;
    reindexPhaseEmbedding: string;
    reindexPhaseEmbeddingCount: string;
    reindexPhaseWriting: string;
    reindexPhaseRoutingSummary: string;
    reindexGraphragModeFull: string;
    reindexGraphragModeIncremental: string;
    reindexGraphragPrepare: string;
    reindexGraphragPipelineStart: string;
    reindexGraphragWorkflowRunning: string;
    reindexGraphragWorkflowDone: string;
    reindexGraphragSubprogress: string;
    reindexGraphragPipelineDone: string;
    reindexStop: string;
    reindexStopped: string;
    /** Toast after refresh when a minimized upload could not be resumed */
    minimizedTaskLostOnRefreshUpload: string;
    /** Toast after refresh when a minimized query could not be resumed */
    minimizedTaskLostOnRefreshQuery: string;
    /** Dock / modal line while polling server after refresh during indexing */
    indexingRecoveredHint: string;
    /** Toast when polling detects indexing finished after refresh */
    indexingRecoveredDone: string;
    embedOk: string;
    queryOk: string;
    queryNeedInput: string;
    queryNeedBase: string;
    chunkCardTitle: string;
    chunkToggle: string;
    chunkStrategy: string;
    chunkStrategyWindow: string;
    chunkStrategyDelimiter: string;
    chunkStrategySemantic: string;
    chunkStrategySmart: string;
    chunkSmartHint: string;
    chunkSmartOverlapChars: string;
    chunkSizeTokens: string;
    chunkOverlapTokens: string;
    chunkDelimiterHint: string;
    chunkMergeUnder: string;
    chunkSemanticMode: string;
    chunkSemanticPack: string;
    chunkSemanticEmbedding: string;
    chunkOverlapSentences: string;
    chunkSimilarity: string;
    chunkMaxChars: string;
    chunkMaxCharsHint: string;
    chunkSave: string;
    chunkReset: string;
    chunkSaveOk: string;
    chunkReindexHint: string;
    /** Top-row workflow: replace corpus + full GraphRAG rebuild */
    corpusReplaceTopHint: string;
    /** Toast after raw/ cleared before re-upload */
    rawClearedForReplace: string;
    appendCorpusToggle: string;
    appendCorpusHintGraphrag: string;
    appendUploadOnly: string;
    graphragIncrementalReindex: string;
  };

  // ── Plugins page ──
  pluginsPage: {
    contextEngineLabel: string;
    dashboardSlots: string;
    disableRuntime: string;
    enableAfterInstall: string;
    enableRuntime: string;
    forceReinstall: string;
    headline: string;
    identifierLabel: string;
    inactive: string;
    installBtn: string;
    installHeading: string;
    installHint: string;
    memoryProviderLabel: string;
    missingEnvWarn: string;
    noDashboardTab: string;
    openTab: string;
    orphanHeading: string;
    pluginListHeading: string;
    providerDefaults: string;
    providersHeading: string;
    providersHint: string;
    refreshDashboard: string;
    removeConfirm: string;
    removeHint: string;
    rescanHeading: string;
    rescanHint: string;
    runtimeHeading: string;
    saveProviders: string;
    savedProviders: string;
    sourceBadge: string;
    authRequired: string;
    authRequiredHint: string;
    updateGit: string;
    versionBadge: string;
    showInSidebar: string;
    hideFromSidebar: string;
  };

  // ── Profiles page ──
  profiles: {
    newProfile: string;
    name: string;
    namePlaceholder: string;
    nameRequired: string;
    nameRule: string;
    invalidName: string;
    cloneFromDefault: string;
    allProfiles: string;
    noProfiles: string;
    defaultBadge: string;
    hasEnv: string;
    model: string;
    skills: string;
    rename: string;
    editSoul: string;
    soulSection: string;
    soulPlaceholder: string;
    saveSoul: string;
    soulSaved: string;
    openInTerminal: string;
    commandCopied: string;
    copyFailed: string;
    confirmDeleteTitle: string;
    confirmDeleteMessage: string;
    created: string;
    deleted: string;
    renamed: string;
  };

  // ── Skills page ──
  skills: {
    title: string;
    searchPlaceholder: string;
    enabledOf: string;
    all: string;
    categories: string;
    filters: string;
    noSkills: string;
    noSkillsMatch: string;
    skillCount: string;
    resultCount: string;
    noDescription: string;
    toolsets: string;
    toolsetLabel: string;
    noToolsetsMatch: string;
    setupNeeded: string;
    disabledForCli: string;
    more: string;
  };

  // ── Config page ──
  config: {
    configPath: string;
    filters: string;
    sections: string;
    exportConfig: string;
    importConfig: string;
    resetDefaults: string;
    resetScopeTooltip: string;
    confirmResetScope: string;
    resetScopeToast: string;
    rawYaml: string;
    searchResults: string;
    fields: string;
    noFieldsMatch: string;
    configSaved: string;
    yamlConfigSaved: string;
    failedToSave: string;
    failedToSaveYaml: string;
    failedToLoadRaw: string;
    configImported: string;
    invalidJson: string;
    categories: {
      general: string;
      agent: string;
      terminal: string;
      display: string;
      delegation: string;
      memory: string;
      compression: string;
      security: string;
      browser: string;
      voice: string;
      tts: string;
      stt: string;
      logging: string;
      discord: string;
      auxiliary: string;
    };
  };

  // ── Env / Keys page ──
  env: {
    changesNote: string;
    confirmClearMessage: string;
    confirmClearTitle: string;
    description: string;
    enterValue: string;
    getKey: string;
    hideAdvanced: string;
    hideValue: string;
    keysCount: string;
    llmProviders: string;
    notConfigured: string;
    notSet: string;
    providersConfigured: string;
    replaceCurrentValue: string;
    showAdvanced: string;
    showValue: string;
  };

  // ── OAuth ──
  oauth: {
    title: string;
    providerLogins: string;
    description: string;
    connected: string;
    expired: string;
    notConnected: string;
    runInTerminal: string;
    noProviders: string;
    login: string;
    disconnect: string;
    managedExternally: string;
    copied: string;
    cli: string;
    copyCliCommand: string;
    connect: string;
    sessionExpires: string;
    initiatingLogin: string;
    exchangingCode: string;
    connectedClosing: string;
    loginFailed: string;
    sessionExpired: string;
    reOpenAuth: string;
    reOpenVerification: string;
    submitCode: string;
    pasteCode: string;
    waitingAuth: string;
    enterCodePrompt: string;
    pkceStep1: string;
    pkceStep2: string;
    pkceStep3: string;
    flowLabels: {
      pkce: string;
      device_code: string;
      external: string;
    };
    expiresIn: string;
  };

  // ── Language switcher ──
  language: {
    switchTo: string;
  };

  // ── Theme switcher ──
  theme: {
    title: string;
    switchTheme: string;
  };
}
