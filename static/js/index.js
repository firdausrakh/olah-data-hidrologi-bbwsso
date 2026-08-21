let tmaChartInstance = null;
    const SERVER_CHUNK_CONFIG = window.SERVER_CHUNK_CONFIG || {beacon_days:25,tatonas_months:3,higertech_months:1,dashindo_months:3};
    let rawData = [];
    let processedData = [];
    let currentFileName = "";
    let currentFile = null;
    let lastServerFetchSignature = "";
    let hasServerFetchResult = false;

    const HOURS_TMA = Array.from({length: 24}, (_, i) => i); 
    const HOURS_CH = [...Array.from({length: 17}, (_, i) => i + 7), ...Array.from({length: 7}, (_, i) => i)];

    const monthMapIndoEng = {
        'januari': 'January', 'februari': 'February', 'maret': 'March',
        'april': 'April', 'mei': 'May', 'juni': 'June',
        'juli': 'July', 'agustus': 'August', 'september': 'September',
        'oktober': 'October', 'november': 'November', 'desember': 'December'
    };

    document.addEventListener('hydro:themechange', () => {
        if (window.__chartState) updateChartTheme();
    });

    function updateChartTheme() {
        if (!window.__chartState) return;
        renderTelemetryChart(window.__chartState);
    }

    const dropArea = document.getElementById('dropArea');

    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropArea.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropArea.classList.remove('dragover');
        }, false);
    });

    dropArea.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;

        if (files.length > 0) {
            const file = files[0];
            const ext = file.name.split('.').pop().toLowerCase();
            const selectedBrand = document.getElementById('brandSelect').value;
            
            if (selectedBrand === 'dashindo' && ext !== 'csv') {
                showStatus("Format file Dashindo tidak valid. Harap unggah file .csv!", false);
                return;
            }
            
            if (['xlsx', 'xls', 'csv'].includes(ext)) {
                document.getElementById('fileInput').files = files;
                processUploadedFile(file);
            } else {
                showStatus("Format file tidak valid. Harap unggah file .xlsx, .xls, atau .csv!", false);
            }
        }
    }, false);

    function showStatus(text, isSuccess) {
        const statusEl = document.getElementById('statusMessage');
        statusEl.textContent = text;
        statusEl.className = 'status ' + (isSuccess ? 'success' : 'error');
    }

    function setLabelTextPreserveHelp(label, text) {
        if (!label) return;
        const textNode = Array.from(label.childNodes).find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
        if (textNode) textNode.textContent = text;
        else label.insertBefore(document.createTextNode(text), label.firstChild);
    }

    function getCurrentSourceMode(){ return document.getElementById('beaconSourceMode')?.value || 'server'; }
    function updateSourceConnectionIndicator(){
        const indicator=document.getElementById('sourceConnectionIndicator');
        if(!indicator) return;
        const serverMode=getCurrentSourceMode()==='server';
        const connected=!!(telemetryAuthCache?.value || window.HydroUI?.authState?.authenticated);
        indicator.style.display=serverMode?'flex':'none';
        indicator.classList.toggle('connected',serverMode&&connected);
        indicator.classList.toggle('disconnected',serverMode&&!connected);
        const live=document.getElementById('sourceLiveIndicator');
        const text=document.getElementById('sourceConnectionText');
        if(live) live.textContent=connected?'LIVE':'OFFLINE';
        if(text) text.textContent=connected?'(Terhubung)':'(Autentikasi diperlukan)';
    }
    function serverCapableBrand(){ const b=document.getElementById('brandSelect')?.value; return b==='all'||b==='beacon'||b==='higertech'||b==='tatonas'||b==='dashindo'; }
    function selectedServerVendor(){
        const brand=document.getElementById('brandSelect')?.value || 'all';
        if(brand!=='all') return (brand==='higertech'||brand==='tatonas'||brand==='dashindo')?brand:'beacon';
        return document.getElementById('beaconPosSelect')?.selectedOptions?.[0]?.dataset?.vendor || 'beacon';
    }
    function selectedLoggerId(){
        const opt=document.getElementById('beaconPosSelect')?.selectedOptions?.[0];
        if(!opt)return '';
        return opt.dataset.idLogger || String(opt.value||'').split('::').slice(1).join('::') || opt.value || '';
    }
    function serverVendor(){ return selectedServerVendor(); }
    function serverPositionsUrl(v=selectedServerVendor()){ return v==='higertech'?'/api/higertech/positions':v==='tatonas'?'/api/tatonas/positions':v==='dashindo'?'/api/dashindo/positions':'/api/positions'; }
    function serverParametersUrl(v=selectedServerVendor()){ return v==='higertech'?'/api/higertech/parameters':v==='tatonas'?'/api/tatonas/parameters':v==='dashindo'?'/api/dashindo/parameters':'/api/parameters'; }
    function serverDataUrl(v=selectedServerVendor()){ return v==='higertech'?'/api/higertech/data':v==='tatonas'?'/api/tatonas/data':v==='dashindo'?'/api/dashindo/data':'/api/beacon/data'; }

    let telemetryAuthPending = false;
    let telemetryAuthCache = {value:false, at:0};
    const SERVER_POSITION_CACHE_TTL = 6 * 60 * 60 * 1000;
    const SERVER_PARAMETER_CACHE_TTL = 6 * 60 * 60 * 1000;
    const serverPositionCache = new Map();
    const serverParameterCache = new Map();
    const inflightServerRequests = new Map();
    const PROCESSING_STATE_KEY = 'hydro.processing.state.v2';
    const PROCESSING_RESULT_CACHE_KEY = 'hydro.processing.result-cache.v1';
    const PROCESSING_RESULT_CACHE_LIMIT = 6;
    const SERVER_SESSION_CACHE_PREFIX = 'hydro.telemetry.metadata.v1.';
    let processingStateReady = false;

    function readSessionJson(key){
        try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch(_err){return null;}
    }
    function writeSessionJson(key,value){
        try{sessionStorage.setItem(key,JSON.stringify(value));return true;}catch(_err){return false;}
    }
    function readProcessingState(){
        const state=readSessionJson(PROCESSING_STATE_KEY);
        return state&&typeof state==='object'?state:null;
    }
    function saveProcessingState(){
        const byId=id=>document.getElementById(id);
        const state={
            brand:byId('brandSelect')?.value||'all',
            dataType:byId('dataTypeSelect')?.value||'tma',
            sourceMode:getCurrentSourceMode(),
            position:byId('beaconPosSelect')?.value||'',
            parameter:byId('beaconParamSelect')?.value||'',
            periodMode:byId('beaconPeriodMode')?.value||'month',
            dailyDate:byId('beaconDailyDate')?.value||'',
            monthPicker:byId('beaconMonthYearPicker')?.value||'',
            month:byId('beaconMonth')?.value||'',
            monthYear:byId('beaconMonthYear')?.value||'',
            yearPicker:byId('beaconYearPicker')?.value||'',
            year:byId('beaconYear')?.value||'',
            customFrom:byId('beaconCustomFrom')?.value||'',
            customTo:byId('beaconCustomTo')?.value||'',
            correctionEnabled:!!byId('correctionEnabled')?.checked,
            correctionValue:byId('correctionInput')?.value||'',
        };
        writeSessionJson(PROCESSING_STATE_KEY,state);
    }

    function processingResultSignature(){
        if(!(serverCapableBrand()&&getCurrentSourceMode()==='server')) return '';
        const requestSignature=currentServerRequestSignature();
        if(!requestSignature) return '';
        const [, sampai]=getBeaconRange();
        const requestedEnd=parseBackendDate(sampai);
        const now=new Date();
        // Hasil periode yang masih berjalan hanya dipakai ulang pada hari yang sama.
        // Periode historis stabil dan aman dipulihkan sepanjang sesi tab.
        const liveDay=requestedEnd && requestedEnd>=now ? getDateISOKey(now) : 'historical';
        return JSON.stringify([
            requestSignature,
            document.getElementById('brandSelect')?.value||'all',
            correctionIsEnabled(),
            getCorrectionValue(),
            liveDay,
        ]);
    }
    function cacheCurrentProcessingResult(){
        const signature=processingResultSignature();
        if(!signature || !Array.isArray(processedData) || !processedData.length) return false;
        const cache=readSessionJson(PROCESSING_RESULT_CACHE_KEY)||{entries:{}};
        cache.entries=cache.entries&&typeof cache.entries==='object'?cache.entries:{};
        cache.entries[signature]={
            at:Date.now(),
            processedData:processedData.map(row=>({...row})),
            currentFileName:currentFileName||'',
        };
        const ordered=Object.entries(cache.entries).sort((a,b)=>(b[1]?.at||0)-(a[1]?.at||0));
        cache.entries=Object.fromEntries(ordered.slice(0,PROCESSING_RESULT_CACHE_LIMIT));
        const text=JSON.stringify(cache);
        // sessionStorage umumnya dibatasi beberapa MB. Pivot bulanan kecil, tetapi
        // tetap beri guard agar cache UI tidak mengganggu penyimpanan state lain.
        if(text.length>3_500_000) return false;
        try{sessionStorage.setItem(PROCESSING_RESULT_CACHE_KEY,text);return true;}catch(_err){return false;}
    }
    function restoreProcessingResultFromCache({announce=true}={}){
        const signature=processingResultSignature();
        if(!signature) return false;
        const cache=readSessionJson(PROCESSING_RESULT_CACHE_KEY);
        const entry=cache?.entries?.[signature];
        if(!entry || !Array.isArray(entry.processedData) || !entry.processedData.length) return false;
        processedData=entry.processedData.map(row=>({...row}));
        currentFileName=entry.currentFileName||currentFileName||'Data Telemetri';
        // Raw response sengaja tidak disimpan agar sessionStorage tetap ringan.
        // Jika pengguna menekan Proses Data secara eksplisit, server tetap dapat
        // diminta ulang; navigasi antar-menu cukup memulihkan hasil pivot ini.
        rawData=[];
        hasServerFetchResult=false;
        lastServerFetchSignature='';
        renderPreviewTable();
        renderSummaryAndChart(document.getElementById('dataTypeSelect')?.value||'tma');
        const downloadBtn=document.getElementById('downloadBtn');
        if(downloadBtn) downloadBtn.disabled=false;
        document.getElementById('downloadCard')?.classList.add('active');
        if(announce){
            showStatus('Hasil terakhir dipulihkan dari cache sesi.',true);
            setBeaconStatus('Hasil olahan terakhir ditampilkan tanpa request ulang.',true);
        }
        return true;
    }
    function sessionMetadataGet(kind,key,ttl){
        const item=readSessionJson(`${SERVER_SESSION_CACHE_PREFIX}${kind}.${key}`);
        if(!item||!item.at||Date.now()-item.at>=ttl)return null;
        return item.value ?? null;
    }
    function sessionMetadataSet(kind,key,value){
        writeSessionJson(`${SERVER_SESSION_CACHE_PREFIX}${kind}.${key}`,{at:Date.now(),value});
    }

    function cachedServerValue(cache,key,ttl){
        const item=cache.get(key);
        if(!item || Date.now()-item.at>=ttl){ if(item)cache.delete(key); return null; }
        return item.value;
    }
    async function dedupedJsonFetch(key,url,options={}){
        if(inflightServerRequests.has(key)) return inflightServerRequests.get(key);
        const job=(async()=>{
            const res=await fetch(url,options);
            const data=await res.json();
            if(!res.ok || !data.ok) throw new Error(data.error||'Request server gagal.');
            return data;
        })();
        inflightServerRequests.set(key,job);
        try{return await job;}finally{inflightServerRequests.delete(key);}
    }
    async function checkTelemetryAuth(force=false){
        if(!force && Date.now()-telemetryAuthCache.at<30000) return telemetryAuthCache.value;
        try{
            const res=await fetch('/api/auth/status',{cache:'no-store'});
            const data=await res.json();
            telemetryAuthCache={value:!!data.authenticated,at:Date.now()};
            const state=document.getElementById('sourceAuthState');
            if(state) state.classList.toggle('active', telemetryAuthCache.value);
            const sourceSelect=document.getElementById('sourceModeSelect');
            const serverOption=sourceSelect?.querySelector('option[value="server"]');
            if(serverOption) serverOption.disabled=!telemetryAuthCache.value;
            if(!telemetryAuthCache.value){
                if(sourceSelect) sourceSelect.value='upload';
                const hidden=document.getElementById('beaconSourceMode'); if(hidden) hidden.value='upload';
            }
            window.HydroUI?.applyAuthState?.(telemetryAuthCache.value, data.configured!==false);
            updateSourceConnectionIndicator();
            return telemetryAuthCache.value;
        }catch(e){ return false; }
    }
    function openTelemetryAuth(){
        telemetryAuthPending=true;
        const modal=document.getElementById('telemetryAuthModal');
        const pwd=document.getElementById('telemetryAppPassword');
        const err=document.getElementById('telemetryAuthError');
        if(err) err.textContent='';
        if(pwd) pwd.value='';
        if(modal){ modal.classList.add('active'); modal.setAttribute('aria-hidden','false'); }
        setTimeout(()=>pwd?.focus(),50);
    }
    function closeTelemetryAuth(cancelled=true){
        const modal=document.getElementById('telemetryAuthModal');
        if(modal){ modal.classList.remove('active'); modal.setAttribute('aria-hidden','true'); }
        telemetryAuthPending=false;
    }
    async function submitTelemetryAuth(){
        const pwd=document.getElementById('telemetryAppPassword')?.value || '';
        const err=document.getElementById('telemetryAuthError');
        if(!pwd){ if(err) err.textContent='Kata sandi wajib diisi.'; return; }
        try{
            const res=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pwd})});
            const data=await res.json();
            if(!res.ok || !data.ok) throw new Error(data.error||'Autentikasi gagal.');
            if(document.getElementById('sourceModeSelect')) document.getElementById('sourceModeSelect').value='server';
            document.getElementById('beaconSourceMode').value='server';
            document.getElementById('sourceAuthState')?.classList.add('active');
            const serverOption=document.getElementById('sourceModeSelect')?.querySelector('option[value="server"]');
            if(serverOption) serverOption.disabled=false;
            telemetryAuthCache={value:true,at:Date.now()};
            window.HydroUI?.applyAuthState?.(true,true);
            updateSourceConnectionIndicator();
            closeTelemetryAuth(false);
            updateSourceVisibility();
            const savedState=readProcessingState();
            const dataType=document.getElementById('dataTypeSelect').value;
            const brand=document.getElementById('brandSelect')?.value||'all';
            if(savedState?.position){
                await loadBeaconPositions(dataType,savedState.position,{parameterId:savedState?.parameter||''});
            }else if(brand==='all' && dataType==='tma'){
                const fastReady=await loadInitialKrangganFast();
                if(fastReady){
                    const keepPosition=document.getElementById('beaconPosSelect')?.value||'';
                    setTimeout(()=>loadBeaconPositions('tma',keepPosition,{silent:true}).catch(()=>{}),500);
                }else{
                    await loadBeaconPositions(dataType);
                }
            }else{
                await loadBeaconPositions(dataType);
            }
            restoreProcessingResultFromCache({announce:true});
        }catch(e){ if(err) err.textContent=e.message||String(e); }
    }
    document.addEventListener('keydown', e=>{ if(e.key==='Enter' && document.getElementById('telemetryAuthModal')?.classList.contains('active')) submitTelemetryAuth(); if(e.key==='Escape' && document.getElementById('telemetryAuthModal')?.classList.contains('active')) closeTelemetryAuth(); });

    async function setSourceMode(mode){
        if(!serverCapableBrand()) return;
        const normalized=mode==='upload'?'upload':'server';
        const hidden=document.getElementById('beaconSourceMode'); const select=document.getElementById('sourceModeSelect');
        if(normalized==='server'){
            const ok=await checkTelemetryAuth();
            if(!ok){
                if(select) select.value='upload';
                if(hidden) hidden.value='upload';
                updateSourceVisibility();
                openTelemetryAuth();
                return;
            }
        }
        if(hidden) hidden.value=normalized; if(select) select.value=normalized;
        updateSourceVisibility();
        updateSourceConnectionIndicator();
        if(normalized==='server') loadBeaconPositions(document.getElementById('dataTypeSelect').value).catch(()=>{});
    }

    function updateCorrectionUI(){
        const dataType=document.getElementById('dataTypeSelect').value, rain=dataType==='rain';
        const lastType=document.body.dataset.correctionType||'';
        const serverLabel=document.getElementById('serverCorrectionLabel'), manualLabel=document.getElementById('correctionLabel');
        const manual=document.getElementById('manualCorrectionInput'), server=document.getElementById('correctionInput');
        if(serverLabel) setLabelTextPreserveHelp(serverLabel, rain?'Faktor Koreksi (Pengali) — opsional':'Faktor Koreksi (meter) — opsional');
        if(manualLabel) setLabelTextPreserveHelp(manualLabel, rain?'Faktor Koreksi (Pengali) — opsional':'Faktor Koreksi (meter) — opsional');
        if(lastType!==dataType){
            if(manual){ manual.value=rain?'1':'0'; manual.placeholder=rain?'1 = tanpa koreksi':'0 = sesuai data asli'; }
            if(server){ server.value=rain?'1':'0'; server.placeholder=rain?'1 = tanpa koreksi':'0 = sesuai data asli'; }
            const ce=document.getElementById('correctionEnabled'), me=document.getElementById('manualCorrectionEnabled');
            if(ce) ce.checked=false; if(me) me.checked=false;
            document.body.dataset.correctionType=dataType;
        }
        if(server) server.disabled=!document.getElementById('correctionEnabled')?.checked;
        if(manual) manual.disabled=!document.getElementById('manualCorrectionEnabled')?.checked;
    }

    function reprocessCorrectionFromCache(){
        if(!(serverCapableBrand()&&getCurrentSourceMode()==='server'))return;
        const signature=currentServerRequestSignature();
        if(!hasServerFetchResult || !signature || signature!==lastServerFetchSignature)return;
        const ok=processLoadedData();
        if(ok!==false){
            setBeaconStatus('Faktor koreksi diterapkan dari data yang sudah dimuat; tidak ada request ulang ke logger.',true);
        }
    }
    function bindCorrectionToggles(){
        [['correctionEnabled','correctionInput'],['manualCorrectionEnabled','manualCorrectionInput']].forEach(([checkId,inputId])=>{
            const check=document.getElementById(checkId), input=document.getElementById(inputId); if(!check)return;
            check.addEventListener('change',()=>{ input.disabled=!check.checked; saveProcessingState(); setTimeout(reprocessCorrectionFromCache,0); });
            input?.addEventListener('change',()=>{saveProcessingState();setTimeout(reprocessCorrectionFromCache,0);});
        });
        updateCorrectionUI();
    }

    function updateSourceVisibility(){
        const brand=document.getElementById('brandSelect').value, mode=getCurrentSourceMode();
        const remote=document.getElementById('beaconRemoteArea'), serverArea=document.getElementById('beaconServerArea'), dropArea=document.getElementById('dropArea'), mapping=document.getElementById('mappingSection');
        const dataType=document.getElementById('dataTypeSelect').value, posLabelText=document.getElementById('beaconPosLabelText'); if(posLabelText) posLabelText.textContent=dataType==='rain'?'Pos Curah Hujan':'Pos Duga Air';
        updateCorrectionUI();
        const sourceGroup=document.getElementById('sourceSelectGroup'); if(serverCapableBrand()){ if(sourceGroup) sourceGroup.style.display='flex'; remote.classList.toggle('active',mode==='server'); serverArea.style.display=mode==='server'?'block':'none'; dropArea.style.display=mode==='upload'?'flex':'none'; mapping.classList.toggle('active',mode==='upload'&&!!currentFile); }
        else { if(sourceGroup) sourceGroup.style.display='none'; remote.classList.remove('active'); serverArea.style.display='none'; dropArea.style.display='flex'; mapping.classList.toggle('active',!!currentFile); }
        updateSourceConnectionIndicator();
        const serverReady=serverCapableBrand()&&mode==='server'&&!!document.getElementById('beaconParamSelect')?.value, manualReady=!!(currentFile&&window.__autoTimeColumn&&window.__autoValueColumn);
        document.getElementById('processBtn').disabled=(serverCapableBrand()&&mode==='server')?!serverReady:!manualReady;
        lucide.createIcons();
    }

    function onDataTypeChange(){
        const dataType=document.getElementById('dataTypeSelect').value;
        updateCorrectionUI();
        updateSummaryLabels(dataType);
        if(serverCapableBrand() && getCurrentSourceMode()==='server'){
            updateSourceVisibility();
            checkTelemetryAuth().then(ok=>{ if(ok) loadBeaconPositions(dataType); });
        }
        if(currentFile){ processUploadedFile(currentFile); }
        updateSourceVisibility();
    }

    function onBrandChange(){
        const dataType=document.getElementById('dataTypeSelect').value;
        const brand=document.getElementById('brandSelect').value;
        const fileInput=document.getElementById('fileInput');
        fileInput.accept=brand==='dashindo'?'.csv':'.xlsx, .xls, .csv';
        updateSummaryLabels(dataType);
        updateCorrectionUI();
        if(serverCapableBrand()){
            if(!document.getElementById('beaconSourceMode').value) document.getElementById('beaconSourceMode').value='server';
            updateSourceVisibility();
            checkTelemetryAuth().then(ok=>{ if(getCurrentSourceMode()==='server' && ok) loadBeaconPositions(dataType); });
            if(currentFile && getCurrentSourceMode()==='upload') processUploadedFile(currentFile);
        } else {
            updateSourceVisibility();
            if(currentFile) processUploadedFile(currentFile);
        }
    }

    function getDateISOKey(dateObj) {
        const year = dateObj.getFullYear();
        const month = String(dateObj.getMonth() + 1).padStart(2, '0');
        const day = String(dateObj.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    function parseISOKeyToDate(isoKey) {
        const parts = isoKey.split('-');
        return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
    }

    function handleFileSelect(event) {
        const file = event.target.files[0];
        if (file) processUploadedFile(file);
    }

    function clearFile(event) {
        if (event) event.stopPropagation();
        
        currentFile = null;
        currentFileName = "";
        rawData = [];
        processedData = [];
        hasServerFetchResult = false;
        lastServerFetchSignature = "";

        document.getElementById('fileInput').value = "";
        document.getElementById('fileNameDisplay').textContent = "Klik atau seret file Excel/CSV ke sini";
        document.getElementById('removeFileBtn').style.display = 'none';

        document.getElementById('mappingSection').classList.remove('active');
        document.getElementById('tableCard').style.display = 'none';
        document.getElementById('chartCard').style.display = 'none';
        document.getElementById('summaryGrid').style.display = 'none';

        document.getElementById('processBtn').disabled = true;
        document.getElementById('downloadBtn').disabled = true;
        document.getElementById('downloadCard').classList.remove('active');
        window.__autoTimeColumn = null;
        window.__autoValueColumn = null;

        if(serverCapableBrand()) updateSourceVisibility();
        showStatus("", true);

        if (tmaChartInstance) {
            tmaChartInstance.destroy();
            tmaChartInstance = null;
        }
        window.__chartState = null;
        setProcessingResultState(false);
        updateProcessingReferenceSummary();
    }

    function populateManualMappings(headers, dataType, brand){
        const timeSelect=document.getElementById('timeColumnSelect');
        const valueSelect=document.getElementById('valueColumnSelect');
        timeSelect.innerHTML=''; valueSelect.innerHTML='';
        headers.forEach(header=>{ const h=String(header).trim(); if(!h)return; timeSelect.add(new Option(h,header)); valueSelect.add(new Option(h,header)); });
        let timeDefault;
        if(brand==='dashindo') timeDefault=headers.find(h=>['_time','Waktu','time','Timestamp','Datetime','Tanggal'].includes(h));
        else if(brand==='higertech') timeDefault=headers.find(h=>['Jam/Menit','Jam','Timestamp','Waktu','Datetime'].includes(String(h).trim()));
        else if(brand==='tatonas') timeDefault=headers.find(h=>['Waktu','Tanggal','Timestamp','Datetime'].some(k=>String(h).trim().toLowerCase().includes(k.toLowerCase())));
        else if(brand==='all') timeDefault=headers.find(h=>/^(?:_?time|waktu|timestamp|datetime|tanggal|jam(?:\/menit)?)$/i.test(String(h).trim())) || headers.find(h=>/waktu|timestamp|datetime|tanggal|jam|_time/i.test(String(h)));
        else timeDefault=headers.find(h=>['Waktu','Tanggal','Timestamp','Datetime','Jam'].some(k=>String(h).trim().toLowerCase().includes(k.toLowerCase())));
        let valueDefault;
        if(dataType==='rain'){
            if(brand==='beacon') valueDefault=headers.find(h=>/precipitation intensity 2|precipitation intensity|akumulasi curah hujan|curah hujan|rainfall|precipitation/i.test(String(h)));
            else if(brand==='dashindo') valueDefault=headers.find(h=>['_value','Curah Hujan','Rainfall','value','Nilai'].includes(h));
            else if(brand==='all') valueDefault=headers.find(h=>/precipitation intensity 2|precipitation intensity|akumulasi curah hujan|curah hujan|rainfall|precipitation|rain intensity|^_?value$|^nilai$/i.test(String(h).trim()));
            else valueDefault=headers.find(h=>/curah hujan|rainfall|precipitation/i.test(String(h)));
        }else{
            if(brand==='dashindo') valueDefault=headers.find(h=>['_value','Tgi Muka Air (m)','Tinggi Muka Air (m)','value','TMA'].includes(h));
            else if(brand==='higertech') valueDefault=headers.find(h=>/TMA|Tinggi Muka Air|Value|Nilai/i.test(String(h)));
            else if(brand==='all') valueDefault=headers.find(h=>/water level|tinggi muka air|tgi muka air|tma|elevasi muka air|^_?value$|^nilai$/i.test(String(h).trim()));
            else valueDefault=headers.find(h=>/water level|tinggi muka air|tma|elevasi muka air/i.test(String(h)));
        }
        if(timeDefault) timeSelect.value=timeDefault;
        if(valueDefault) valueSelect.value=valueDefault;
        syncManualMapping();
        document.getElementById('mappingSection').classList.add('active');
    }

    function autoMapColumns(headers, parameterName='', dataType='', brand=''){
        const clean=headers.filter(Boolean).map(h=>String(h).trim());
        let timeCol=clean.find(h=>/^(waktu|timestamp|datetime|tanggal|jam|jam\/menit|_time|time)$/i.test(h)) || clean.find(h=>/waktu|timestamp|datetime|tanggal|jam|_time|time/i.test(h));
        let valueCol=''; const p=String(parameterName||'').toLowerCase();
        if(p) valueCol=clean.find(h=>h.toLowerCase()===p) || clean.find(h=>h.toLowerCase().includes(p) || p.includes(h.toLowerCase()));
        if(!valueCol && dataType==='rain') valueCol=clean.find(h=>/precipitation intensity 2|precipitation intensity|curah hujan|rainfall|rain intensity|precipitation/i.test(h));
        if(!valueCol && dataType==='tma') valueCol=clean.find(h=>/water level|tinggi muka air|elevasi muka air|muka air|stage|elv\.?\s*ma/i.test(h));
        if(!valueCol){ const candidates=clean.filter(h=>h!==timeCol); valueCol=candidates.find(h=>rawData.some(r=>String(r[h]??'').trim()!=='' && !isNaN(parseFloat(String(r[h]).replace(/[^0-9.-]/g,''))))) || candidates[0] || ''; }
        window.__autoTimeColumn=timeCol||''; window.__autoValueColumn=valueCol||'';
        const manualVisible=!serverCapableBrand() || getCurrentSourceMode()==='upload';
        if(manualVisible) populateManualMappings(clean,dataType,brand); else document.getElementById('mappingSection').classList.remove('active');
        document.getElementById('processBtn').disabled=!timeCol||!valueCol;
        if(timeCol && valueCol) showStatus(`Data siap diproses otomatis: ${timeCol} → ${valueCol}.`,true);
    }

    function syncManualMapping(){
        const time=document.getElementById('timeColumnSelect'); const value=document.getElementById('valueColumnSelect'); if(!time||!value)return;
        window.__autoTimeColumn=time.value; window.__autoValueColumn=value.value;
        const isManual=!serverCapableBrand() || getCurrentSourceMode()==='upload';
        document.getElementById('processBtn').disabled=isManual ? !(currentFile&&time.value&&value.value) : !value.value;
    }

    function processUploadedFile(file) {
        currentFile=file;
        hasServerFetchResult=false;
        lastServerFetchSignature='';
        currentFileName=file.name.replace(/\.[^/.]+$/, '');
        document.getElementById('fileNameDisplay').textContent=file.name;
        document.getElementById('removeFileBtn').style.display='flex';
        showStatus('Membaca file...',true);
        const ext=file.name.split('.').pop().toLowerCase();
        const brand=document.getElementById('brandSelect').value;
        const dataType=document.getElementById('dataTypeSelect').value;
        const ready=(rows,headers)=>{
            rawData=rows;
            autoMapColumns(headers,'',dataType,brand);
            showStatus(`${rows.length.toLocaleString('id-ID')} baris siap diproses.`,true);
        };
        if(ext==='csv'){
            Papa.parse(file,{header:true,skipEmptyLines:true,complete:results=>{
                if(!results.data.length){showStatus('File CSV kosong.',false);return;}
                ready(results.data,Object.keys(results.data[0]||{}));
            },error:()=>showStatus('Gagal membaca file CSV.',false)});
        }else{
            const reader=new FileReader();
            reader.onload=e=>{
                try{
                    const data=new Uint8Array(e.target.result);
                    const workbook=XLSX.read(data,{type:'array',cellDates:false,raw:false});
                    const tatonasLike=(brand==='tatonas'||brand==='all') && workbook.SheetNames.includes('Semua');
                    let worksheet=tatonasLike?workbook.Sheets['Semua']:workbook.Sheets[workbook.SheetNames[0]];
                    const matrix=XLSX.utils.sheet_to_json(worksheet,{header:1,defval:''});
                    let headerIndex=-1;
                    if(tatonasLike && matrix.length>=10) headerIndex=9;
                    else {
                        for(let i=0;i<Math.min(matrix.length,30);i++){
                            const rowStr=matrix[i].map(cell=>String(cell).toLowerCase().trim()).join(' ');
                            if(/waktu|jam|timestamp|tanggal|datetime|_time/.test(rowStr)){headerIndex=i;break;}
                        }
                    }
                    if(headerIndex<0) throw new Error('Tidak dapat menemukan header waktu pada file Excel.');
                    const headers=matrix[headerIndex].map(h=>String(h).trim());
                    const rows=[];
                    for(let i=headerIndex+1;i<matrix.length;i++){
                        const row=matrix[i]; if(!row||!row.length) continue;
                        const obj={}; let has=false;
                        headers.forEach((h,idx)=>{if(h){obj[h]=row[idx]??'';if(String(obj[h]).trim()!=='')has=true;}});
                        if(has) rows.push(obj);
                    }
                    if(!rows.length) throw new Error('Tidak ada data pada file Excel.');
                    ready(rows,headers.filter(Boolean));
                }catch(err){showStatus(err.message||String(err),false);}
            };
            reader.readAsArrayBuffer(file);
        }
    }

    function parseDateTimeStrict(dateVal, brand) {
        if (!dateVal) return null;

        let str = String(dateVal).trim();

        if (brand === 'higertech' || brand === 'all') {
            Object.keys(monthMapIndoEng).forEach(indo => {
                const reg = new RegExp(indo, 'gi');
                str = str.replace(reg, monthMapIndoEng[indo]);
            });
            if (/\b\d{1,2}\.\d{2}$/.test(str)) str = str.replace(/(\d{1,2})\.(\d{2})$/, '$1:$2');
        }

        let hour = null;
        let timeMatch = str.match(/(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?/i);
        if (timeMatch) {
            hour = parseInt(timeMatch[1], 10);
            let period = timeMatch[4] ? timeMatch[4].toUpperCase() : null;

            if (period === 'PM' && hour < 12) hour += 12;
            if (period === 'AM' && hour === 12) hour = 0;
        }

        let parsedDate = new Date(str);
        
        if (isNaN(parsedDate.getTime())) {
            let num = parseFloat(str);
            if (!isNaN(num)) {
                let utc_days  = Math.floor(num - 25569);
                let utc_value = utc_days * 86400;
                let date_info = new Date(utc_value * 1000);
                
                let fractional_day = num - Math.floor(num) + 0.0000001;
                let total_seconds = Math.floor(86400 * fractional_day);
                
                if (hour === null) {
                    hour = Math.floor(total_seconds / 3600);
                }
                
                parsedDate = new Date(date_info.getFullYear(), date_info.getMonth(), date_info.getDate());
            }
        }

        if (isNaN(parsedDate.getTime())) return null;

        if (hour === null) {
            hour = parsedDate.getHours();
        }

        return {
            dateObj: parsedDate,
            hour: hour
        };
    }

    function resetBeaconInputs(){
        const pos=document.getElementById('beaconPosSelect');
        const param=document.getElementById('beaconParamSelect');
        if(pos) pos.value='';
        if(param){param.innerHTML='<option value="">Pilih pos terlebih dahulu</option>';param.disabled=true;}
        setBeaconStatus('',true);
        updateSourceVisibility();
    }
    function setBeaconStatus(text,ok){const el=document.getElementById('beaconStatus');if(!el)return;el.textContent=text||'';el.className='status '+(ok?'success':'error');}
    function preferredParameter(parameters,dataType){
        const list=Array.isArray(parameters)?parameters:[];
        const score=p=>{
            const n=String(p.name||'').toLowerCase();
            if(dataType==='rain'){
                const numbered=n.match(/(?:precipitation\s*intensity|curah\s*hujan|rainfall|precipitation|rain\s*intensity)[\s_#-]*(\d+)\b/);
                if(numbered && Number(numbered[1])===2)return 1200;
                if(/precipitation\s*intensity/.test(n))return 1000;
                if(/curah hujan|rainfall|precipitation|rain intensity/.test(n))return 900;
            } else {
                if(/tinggi muka air/.test(n))return 1000;if(/water level/.test(n))return 950;if(/elevasi muka air/.test(n))return 900;if(/water stage|stage|muka air|elv\.?\s*ma/.test(n))return 850;
            }
            return 100;
        };
        return [...list].sort((a,b)=>score(b)-score(a)||String(a.name||'').localeCompare(String(b.name||''),'id'))[0]||null;
    }
    window.__serverParametersByPosition = window.__serverParametersByPosition || {};
    window.__serverParameterMap = window.__serverParameterMap || {};

    function renderServerParameters(list,preferredId=''){
        const param=document.getElementById('beaconParamSelect');
        const dataType=document.getElementById('dataTypeSelect').value;
        const items=Array.isArray(list)?list:[];
        param.innerHTML='';
        window.__serverParameterMap={};
        items.forEach(p=>{
            window.__serverParameterMap[String(p.id)]=p;
            const opt=new Option(p.name,p.id);
            opt.dataset.unit=p.unit||'';
            opt.dataset.sourceUnit=p.source_unit||p.unit||'';
            opt.dataset.type=p.type||'';
            param.add(opt);
        });
        if(!items.length){
            param.innerHTML='<option value="">Tidak ada parameter</option>';
            param.disabled=true;
            updateSourceVisibility();
            return false;
        }
        const preferredText=String(preferredId||'');
        if(preferredText && items.some(p=>String(p.id)===preferredText)) param.value=preferredText;
        else { const pref=preferredParameter(items,dataType); if(pref)param.value=pref.id; }
        param.disabled=false;
        window.__activeServerParameter=window.__serverParameterMap[param.value]||null;
        updateSummaryLabels(dataType);
        updateSourceVisibility();
        updateProcessingReferenceSummary();
        return true;
    }

    async function fetchPositionDataForVendor(vendor,dataType){
        const cacheKey=vendor+'|'+dataType;
        let data=cachedServerValue(serverPositionCache,cacheKey,SERVER_POSITION_CACHE_TTL);
        if(!data){
            data=sessionMetadataGet('positions',cacheKey,SERVER_POSITION_CACHE_TTL);
            if(data) serverPositionCache.set(cacheKey,{at:Date.now(),value:data});
        }
        if(!data){
            data=await dedupedJsonFetch('positions|'+cacheKey,serverPositionsUrl(vendor)+'?data_type='+encodeURIComponent(dataType),{cache:'no-store'});
            if(data.ready!==false){
                serverPositionCache.set(cacheKey,{at:Date.now(),value:data});
                sessionMetadataSet('positions',cacheKey,data);
            }
        }
        return data;
    }

    async function loadInitialKrangganFast(){
        const pos=document.getElementById('beaconPosSelect');
        if(!pos || document.getElementById('brandSelect')?.value!=='all' || document.getElementById('dataTypeSelect')?.value!=='tma') return false;
        pos.disabled=true;
        pos.innerHTML='<option value="">Memuat Pos Duga Air Kranggan...</option>';
        setBeaconStatus('Menyiapkan data awal Kranggan...',true);
        try{
            const data=await fetchPositionDataForVendor('higertech','tma');
            const positions=Array.isArray(data.positions)?data.positions:[];
            const kranggan=positions.find(item=>/\bkranggan\b/i.test(String(item.name||item.location||'')));
            if(!kranggan) return false;
            pos.innerHTML='';
            window.__serverParametersByPosition={};
            const group=document.createElement('optgroup');
            group.label='Higertech';
            positions.forEach(item=>{
                const id=String(item.id_logger ?? item.id ?? item.deviceId ?? '');
                if(!id) return;
                const value='higertech::'+id;
                const opt=new Option(item.name||item.location||id,value);
                opt.dataset.vendor='higertech';
                opt.dataset.idLogger=id;
                group.appendChild(opt);
                if(Array.isArray(item.parameters)&&item.parameters.length){
                    window.__serverParametersByPosition[value]=item.parameters;
                    serverParameterCache.set('higertech|tma|'+id,{at:Date.now(),value:item.parameters});
                    sessionMetadataSet('parameters','higertech|tma|'+id,item.parameters);
                }
            });
            pos.appendChild(group);
            const target=[...pos.options].find(opt=>/\bkranggan\b/i.test(String(opt.textContent||'')));
            if(!target) return false;
            pos.value=target.value;
            pos.disabled=false;
            await loadBeaconParameters();
            setBeaconStatus('Pos Duga Air Kranggan siap dipilih.', true);
            return true;
        }catch(err){
            console.warn('Initial Kranggan preload gagal:',err);
            return false;
        }finally{
            pos.disabled=false;
        }
    }

    async function loadBeaconPositions(dataType,preserveId='',options={}){
        if(!(await checkTelemetryAuth())) return;
        const pos=document.getElementById('beaconPosSelect');if(!pos)return;
        const prev=preserveId||pos.value||'';
        const selectedBrand=document.getElementById('brandSelect')?.value||'all';
        const vendors=selectedBrand==='all'?['beacon','tatonas','higertech','dashindo']:[selectedServerVendor()];
        if(!options.silent){
            pos.disabled=true;
            pos.innerHTML='<option value="">Memuat daftar pos...</option>';
        }
        if(!options.silent) setBeaconStatus(selectedBrand==='all'?'Memuat daftar pos dari seluruh logger...':'Memuat daftar pos...',true);
        try{
            const settled=await Promise.allSettled(vendors.map(v=>fetchPositionDataForVendor(v,dataType).then(data=>({vendor:v,data}))));
            const successful=settled.filter(x=>x.status==='fulfilled').map(x=>x.value);
            if(!successful.length){
                const reason=settled.find(x=>x.status==='rejected')?.reason;
                throw reason||new Error('Daftar pos tidak tersedia.');
            }
            pos.innerHTML='';
            window.__serverParametersByPosition={};
            const vendorLabels={beacon:'Beacon',tatonas:'Tatonas',higertech:'Higertech',dashindo:'Dashindo'};
            successful.forEach(({vendor,data})=>{
                const parent=selectedBrand==='all'?document.createElement('optgroup'):pos;
                if(selectedBrand==='all') parent.label=vendorLabels[vendor]||vendor;
                (data.positions||[]).forEach(p=>{
                    const id=String(p.id_logger ?? p.id ?? p.deviceId ?? '');
                    if(!id)return;
                    const value=selectedBrand==='all'?vendor+'::'+id:id;
                    const opt=new Option(p.name||p.location||id,value);
                    opt.dataset.vendor=vendor;
                    opt.dataset.idLogger=id;
                    parent.appendChild(opt);
                    if(Array.isArray(p.parameters)&&p.parameters.length){
                        window.__serverParametersByPosition[value]=p.parameters;
                        serverParameterCache.set(vendor+'|'+dataType+'|'+id,{at:Date.now(),value:p.parameters});
                        sessionMetadataSet('parameters',vendor+'|'+dataType+'|'+id,p.parameters);
                    }
                });
                if(selectedBrand==='all' && parent.children.length)pos.appendChild(parent);
            });
            if(!pos.options.length)pos.add(new Option('Tidak ada pos sesuai kategori',''));
            const defaultKranggan=!prev && (selectedBrand==='all'||selectedBrand==='higertech') && dataType==='tma'
                ? [...pos.options].find(o=>/\bkranggan\b/i.test(String(o.textContent||'')) && (selectedBrand==='higertech'||o.dataset.vendor==='higertech'))
                : null;
            if(defaultKranggan) pos.value=defaultKranggan.value;
            else if(prev&&[...pos.options].some(o=>o.value===prev))pos.value=prev;
            pos.disabled=false;
            if(pos.value)await loadBeaconParameters(options.parameterId||'');
            const failures=settled.filter(x=>x.status==='rejected').length;
            if(!options.silent) setBeaconStatus(failures?`${successful.length} kelompok logger dimuat; ${failures} kelompok belum tersedia.`:'',failures===0);
            saveProcessingState();
            if(successful.some(x=>x.data.ready===false&&x.data.warming))setTimeout(()=>loadBeaconPositions(dataType,pos.value,options).catch(()=>{}),1800);
        }catch(err){
            if(!options.silent){
                pos.innerHTML='<option value="">Gagal memuat pos</option>';
                pos.disabled=false;
                setBeaconStatus(err.message||String(err),false);
                updateSourceVisibility();
            }
        }
    }


    async function loadBeaconParameters(preferredId=''){
        if(typeof preferredId!=='string') preferredId='';
        const pos=document.getElementById('beaconPosSelect'),param=document.getElementById('beaconParamSelect'),dataType=document.getElementById('dataTypeSelect').value;
        if(!pos||!param)return;
        if(!pos.value){param.innerHTML='<option value="">Pilih pos terlebih dahulu</option>';param.disabled=true;updateSourceVisibility();return;}

        const vendor=selectedServerVendor();
        const idLogger=selectedLoggerId();
        const positionKey=String(pos.value);
        const parameterKey=vendor+'|'+dataType+'|'+idLogger;
        const embedded=window.__serverParametersByPosition?.[positionKey];
        let cached=Array.isArray(embedded)&&embedded.length ? embedded : cachedServerValue(serverParameterCache,parameterKey,SERVER_PARAMETER_CACHE_TTL);
        if(!cached){
            cached=sessionMetadataGet('parameters',parameterKey,SERVER_PARAMETER_CACHE_TTL);
            if(cached) serverParameterCache.set(parameterKey,{at:Date.now(),value:cached});
        }
        if(Array.isArray(cached)&&cached.length){
            window.__serverParametersByPosition[positionKey]=cached;
            renderServerParameters(cached,preferredId);
            setBeaconStatus('',true);
            saveProcessingState();
            return;
        }

        param.disabled=true;param.innerHTML='<option value="">Memuat parameter...</option>';
        setBeaconStatus('Memeriksa parameter pos...',true);
        try{
            const paramUrl=serverParametersUrl(vendor)+'?id_logger='+encodeURIComponent(idLogger)+'&data_type='+encodeURIComponent(dataType);
            const data=await dedupedJsonFetch('parameters|'+parameterKey,paramUrl,{cache:'no-store'});
            const list=data.all_parameters||data.parameters||[];
            if(list.length){
                window.__serverParametersByPosition[positionKey]=list;
                serverParameterCache.set(parameterKey,{at:Date.now(),value:list});
                sessionMetadataSet('parameters',parameterKey,list);
            }
            renderServerParameters(list,preferredId);
            setBeaconStatus('',true);
            saveProcessingState();
        }catch(err){
            param.innerHTML='<option value="">Gagal memuat parameter</option>';param.disabled=false;
            setBeaconStatus(err.message||String(err),false);
            updateSourceVisibility();
        }
    }

    const pad2 = window.HydroUI?.pad2 || (n => String(n).padStart(2,'0'));
    function formatBackendDate(d){return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate())+' '+pad2(d.getHours())+':'+pad2(d.getMinutes());}
    function dayRange(){const d=document.getElementById('beaconDailyDate').value;if(!d)return['',''];if(document.getElementById('dataTypeSelect').value==='rain'){const a=new Date(d+'T07:00:00'),b=new Date(d+'T00:00:00');b.setDate(b.getDate()+1);b.setHours(6,59,0,0);return[formatBackendDate(a),formatBackendDate(b)];}return[d+' 00:00',d+' 23:59'];}
    function monthRange(){const y=parseInt(document.getElementById('beaconMonthYear').value,10),m=parseInt(document.getElementById('beaconMonth').value,10)-1;if(!Number.isFinite(y)||!Number.isFinite(m))return['',''];if(document.getElementById('dataTypeSelect').value==='rain')return[formatBackendDate(new Date(y,m,1,7,0)),formatBackendDate(new Date(y,m+1,1,6,59))];return[formatBackendDate(new Date(y,m,1,0,0)),formatBackendDate(new Date(y,m+1,0,23,59))];}
    function yearRange(){const y=parseInt(document.getElementById('beaconYear').value,10);if(!Number.isFinite(y))return['',''];if(document.getElementById('dataTypeSelect').value==='rain')return[formatBackendDate(new Date(y,0,1,7,0)),formatBackendDate(new Date(y+1,0,1,6,59))];return[formatBackendDate(new Date(y,0,1,0,0)),formatBackendDate(new Date(y,11,31,23,59))];}
    function customRange(){const f=document.getElementById('beaconCustomFrom').value,t=document.getElementById('beaconCustomTo').value;if(!f||!t)return['',''];if(document.getElementById('dataTypeSelect').value==='rain'){const a=new Date(f+'T07:00:00'),b=new Date(t+'T00:00:00');b.setDate(b.getDate()+1);b.setHours(6,59,0,0);return[formatBackendDate(a),formatBackendDate(b)];}return[f+' 00:00',t+' 23:59'];}
    function getBeaconRange(){const mode=document.getElementById('beaconPeriodMode').value;return mode==='day'?dayRange():mode==='month'?monthRange():mode==='year'?yearRange():customRange();}
    function currentServerRequestSignature(){
        if(!(serverCapableBrand()&&getCurrentSourceMode()==='server'))return '';
        const [dari,sampai]=getBeaconRange();
        return JSON.stringify([
            selectedServerVendor(), selectedLoggerId(), document.getElementById('beaconParamSelect')?.value||'',
            document.getElementById('dataTypeSelect')?.value||'', document.getElementById('beaconPeriodMode')?.value||'', dari, sampai
        ]);
    }
    function onBeaconPeriodModeChange(){const mode=document.getElementById('beaconPeriodMode').value;document.getElementById('beaconDailyWrap').style.display=mode==='day'?'flex':'none';document.getElementById('beaconMonthWrap').style.display=mode==='month'?'flex':'none';document.getElementById('beaconYearWrap').style.display=mode==='year'?'flex':'none';document.getElementById('beaconCustomFromWrap').style.display=mode==='custom'?'flex':'none';document.getElementById('beaconCustomToWrap').style.display=mode==='custom'?'flex':'none';}
    function localDateInput(d){return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate());}
    function initBootstrapPeriodPickers(){
        const now=new Date();
        const monthHidden=document.getElementById('beaconMonth'),monthYearHidden=document.getElementById('beaconMonthYear'),yearHidden=document.getElementById('beaconYear');
        const monthInput=document.getElementById('beaconMonthYearPicker'),yearInput=document.getElementById('beaconYearPicker');
        const dayInput=document.getElementById('beaconDailyDate'),fromInput=document.getElementById('beaconCustomFrom'),toInput=document.getElementById('beaconCustomTo');
        if(!monthHidden||!monthYearHidden||!yearHidden||!monthInput||!yearInput||!dayInput||!fromInput||!toInput)return;
        monthHidden.value=String(now.getMonth()+1);monthYearHidden.value=String(now.getFullYear());yearHidden.value=String(now.getFullYear());
        const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
        const monthStart=new Date(now.getFullYear(),now.getMonth(),1),monthEnd=new Date(now.getFullYear(),now.getMonth()+1,0);
        const defaultRangeEnd=monthEnd>today?today:monthEnd;

        if(window.jQuery&&jQuery.fn&&jQuery.fn.datepicker){
            const base={language:'id',autoclose:true,todayHighlight:true,enableOnReadonly:true,orientation:'bottom auto',endDate:today};
            const $day=jQuery(dayInput),$from=jQuery(fromInput),$to=jQuery(toInput),$month=jQuery(monthInput),$year=jQuery(yearInput);
            [$day,$from,$to,$month,$year].forEach($el=>{try{$el.datepicker('destroy');}catch(_){}});
            $day.datepicker({...base,format:'yyyy-mm-dd',startView:'days',minViewMode:'days'})
                .on('changeDate.periodDay',()=>{if(processingStateReady)saveProcessingState();});
            $from.datepicker({...base,format:'yyyy-mm-dd',startView:'days',minViewMode:'days'})
                .on('changeDate.periodRange',function(e){if(e.date){$to.datepicker('setStartDate',e.date);const end=$to.datepicker('getDate');if(end&&end<e.date)$to.datepicker('setDate',e.date);}if(processingStateReady)saveProcessingState();});
            $to.datepicker({...base,format:'yyyy-mm-dd',startView:'days',minViewMode:'days'})
                .on('changeDate.periodRange',function(e){if(e.date)$from.datepicker('setEndDate',e.date);if(processingStateReady)saveProcessingState();});
            $month.datepicker({...base,format:'MM yyyy',startView:'months',minViewMode:'months'})
                .on('changeDate.periodMonth',function(e){const d=e.date||now;monthHidden.value=String(d.getMonth()+1);monthYearHidden.value=String(d.getFullYear());if(processingStateReady)saveProcessingState();});
            $year.datepicker({...base,format:'yyyy',startView:'years',minViewMode:'years',todayHighlight:false})
                .on('changeDate.periodYear',function(e){const d=e.date||now;yearHidden.value=String(d.getFullYear());if(processingStateReady)saveProcessingState();});
            $day.datepicker('setDate',today);$from.datepicker('setDate',monthStart);$to.datepicker('setDate',defaultRangeEnd);$month.datepicker('setDate',today);$year.datepicker('setDate',today);
        }else{
            // Native/freetext fallback when the datepicker CDN is unavailable.
            [dayInput,fromInput,toInput,monthInput,yearInput].forEach(el=>el.readOnly=false);
            dayInput.value=localDateInput(today);fromInput.value=localDateInput(monthStart);toInput.value=localDateInput(defaultRangeEnd);
            monthInput.value=pad2(now.getMonth()+1)+'/'+now.getFullYear();yearInput.value=String(now.getFullYear());
            monthInput.addEventListener('change',()=>{const m=monthInput.value.match(/(\d{1,2}).*?(\d{4})/);if(m){monthHidden.value=String(Math.max(1,Math.min(12,Number(m[1]))));monthYearHidden.value=m[2];}});
            yearInput.addEventListener('change',()=>{const m=yearInput.value.match(/\d{4}/);if(m)yearHidden.value=m[0];});
        }
    }
    function populateBeaconMonths(){initBootstrapPeriodPickers();onBeaconPeriodModeChange();}
    function rowsToObjects(headers,rows){return(rows||[]).map(r=>{const o={};(headers||[]).forEach((h,i)=>o[h]=r[i]??'');return o;});}
    function parseBackendDate(value){
        const m=String(value||'').trim().match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
        if(!m)return null;
        return new Date(Number(m[1]),Number(m[2])-1,Number(m[3]),Number(m[4]||0),Number(m[5]||0),0,0);
    }
    function requestedTableDateBounds(){
        if(!(serverCapableBrand()&&getCurrentSourceMode()==='server'))return null;
        const mode=document.getElementById('beaconPeriodMode')?.value;
        const todayKey=getDateISOKey(new Date());
        if(mode==='month'){
            const y=Number(document.getElementById('beaconMonthYear')?.value),m=Number(document.getElementById('beaconMonth')?.value)-1;
            if(!Number.isFinite(y)||!Number.isFinite(m))return null;
            const startKey=getDateISOKey(new Date(y,m,1));
            const requestedEnd=getDateISOKey(new Date(y,m+1,0));
            return [startKey,requestedEnd>todayKey?todayKey:requestedEnd];
        }
        if(mode==='year'){
            const y=Number(document.getElementById('beaconYear')?.value);
            if(!Number.isFinite(y))return null;
            const startKey=getDateISOKey(new Date(y,0,1));
            const requestedEnd=getDateISOKey(new Date(y,11,31));
            return [startKey,requestedEnd>todayKey?todayKey:requestedEnd];
        }
        return null;
    }
    function splitServerRequestRange(vendor,dari,sampai){
        const start=parseBackendDate(dari),requestedEnd=parseBackendDate(sampai);
        if(!start||!requestedEnd||requestedEnd<start)return [];
        const now=new Date(),end=requestedEnd>now?now:requestedEnd;
        if(end<start)return [];
        const chunks=[];
        let cursor=new Date(start);
        while(cursor<=end){
            let boundary;
            if(vendor==='beacon'){
                const days=Math.max(1,Number(SERVER_CHUNK_CONFIG.beacon_days)||25);
                boundary=new Date(cursor); boundary.setDate(boundary.getDate()+days);
            }else{
                const key=vendor==='tatonas'?'tatonas_months':vendor==='dashindo'?'dashindo_months':'higertech_months';
                const months=Math.max(1,Number(SERVER_CHUNK_CONFIG[key])||1);
                boundary=new Date(cursor.getFullYear(),cursor.getMonth()+months,1,0,0,0,0);
                if(boundary<=cursor){boundary=new Date(cursor);boundary.setMonth(boundary.getMonth()+months);}
            }
            let chunkEnd=new Date(Math.min(end.getTime(),boundary.getTime()-60000));
            if(chunkEnd<cursor)chunkEnd=new Date(end);
            chunks.push([formatBackendDate(cursor),formatBackendDate(chunkEnd)]);
            cursor=new Date(chunkEnd.getTime()+60000);
        }
        return chunks;
    }
    async function fetchServerParts(parts,requestPart,onProgress){
        if(!parts.length)return [];
        const concurrency=Math.max(1,Math.min(parts.length,2));
        const results=new Array(parts.length);let next=0,done=0;
        const worker=async()=>{
            while(true){
                const idx=next++; if(idx>=parts.length)return;
                results[idx]=await requestPart(parts[idx],idx);
                done++; onProgress?.(done,parts.length);
            }
        };
        await Promise.all(Array.from({length:concurrency},worker));
        return results;
    }
    let processProgressHideTimer=null;
    function setProcessProgress(label,state='active',percent=null){
        const box=document.getElementById('processProgress'),text=document.getElementById('processProgressLabel'),hint=document.getElementById('processProgressHint'),bar=document.getElementById('processProgressBar');
        if(!box||!text)return;
        if(processProgressHideTimer){clearTimeout(processProgressHideTimer);processProgressHideTimer=null;}
        box.classList.remove('active','complete','error','indeterminate');
        box.classList.add('active');
        const hasPercent=Number.isFinite(Number(percent));
        if(state==='complete')box.classList.add('complete');
        else if(state==='error')box.classList.add('error');
        else if(!hasPercent)box.classList.add('indeterminate');
        text.textContent=label||'Memproses data...';
        if(bar && hasPercent)bar.style.width=Math.max(0,Math.min(100,Number(percent)))+'%';
        else if(bar && state!=='complete'&&state!=='error')bar.style.width='';
        if(hint)hint.textContent=state==='complete'?'Selesai':state==='error'?'Gagal':hasPercent?Math.round(Number(percent))+'%':'Sedang berjalan';
    }
    function hideProcessProgress(delay=550){
        const box=document.getElementById('processProgress');
        if(!box)return;
        processProgressHideTimer=setTimeout(()=>{box.classList.remove('active','complete','error');},delay);
    }

    async function fetchBeaconData(){
        const id_logger=selectedLoggerId(),id_param=document.getElementById('beaconParamSelect').value,[dari,sampai]=getBeaconRange();
        if(!id_logger||!id_param)throw new Error('Pilih pos dan parameter terlebih dahulu.');
        if(!dari||!sampai)throw new Error('Periode belum lengkap.');
        const vendor=serverVendor(),vendorLabel=vendor==='higertech'?'Higertech':vendor==='tatonas'?'Tatonas':vendor==='dashindo'?'Dashindo':'Beacon';
        const selectedName=document.getElementById('beaconParamSelect').selectedOptions?.[0]?.textContent||'';
        const parts=splitServerRequestRange(vendor,dari,sampai);
        setBeaconStatus('Mengambil data dari server '+vendorLabel+'...',true);
        setProcessProgress('Mengambil data dari server '+vendorLabel+'...','active',parts.length?0:100);
        const payloadBase={id_logger,id_param,data_type:document.getElementById('dataTypeSelect').value,period_mode:document.getElementById('beaconPeriodMode')?.value||''};
        const responses=await fetchServerParts(parts,async([partFrom,partTo])=>{
            const res=await fetch(serverDataUrl(vendor),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payloadBase,dari:partFrom,sampai:partTo})});
            let data={}; try{data=await res.json();}catch(_e){}
            if(!res.ok||!data.ok)throw new Error(data.error||'Data server gagal diambil.');
            return data;
        },(done,total)=>setProcessProgress('Mengambil data dari server '+vendorLabel+'...','active',Math.round(done/total*100)));
        const firstMeta=responses.find(x=>x?.parameter)||{};
        const headerSet=new Set(); rawData=[];
        responses.forEach(data=>{(data.headers||[]).forEach(h=>headerSet.add(h));rawData.push(...rowsToObjects(data.headers||[],data.rows||[]));});
        const headers=[...headerSet];
        window.__autoTimeColumn=headers.find(h=>/waktu|timestamp|datetime|tanggal|jam|time/i.test(h))||headers[0]||'Waktu';
        window.__activeServerParameter=firstMeta.parameter||window.__serverParameterMap?.[id_param]||null;
        window.__autoValueColumn=headers.find(h=>String(h).toLowerCase()===selectedName.toLowerCase())||headers.find(h=>String(h).toLowerCase().includes(selectedName.toLowerCase())||selectedName.toLowerCase().includes(String(h).toLowerCase()))||'';
        if(!window.__autoValueColumn){window.__autoValueColumn=headers.find(h=>document.getElementById('dataTypeSelect').value==='rain'?/precipitation|curah hujan|rainfall|rain intensity/i.test(h):/water level|tinggi muka air|elevasi muka air|muka air|stage|elv\.?\s*ma/i.test(h))||selectedName||'Nilai';}
        const startDateOnly=String(dari).slice(0,10),requestedEndDateOnly=String(sampai).slice(0,10),todayKey=getDateISOKey(new Date()),endDateOnly=requestedEndDateOnly>todayKey?todayKey:requestedEndDateOnly,posName=responses.find(x=>x?.pos_name)?.pos_name||vendorLabel;
        currentFileName=posName+' - '+selectedName+' - '+startDateOnly+' - '+endDateOnly;
        const requestedBounds=requestedTableDateBounds();
        if(!rawData.length && !requestedBounds)throw new Error('Tidak ada data pada rentang yang diminta.');
        if(headers.length)autoMapColumns(headers,selectedName,document.getElementById('dataTypeSelect').value,vendor);
        setBeaconStatus(rawData.length?`${rawData.length.toLocaleString('id-ID')} baris diterima.`:'Periode dimuat tanpa data; tanggal tetap dipertahankan pada hasil.',true);
        lastServerFetchSignature=currentServerRequestSignature();
        hasServerFetchResult=true;
        updateSourceVisibility();
    }

    async function executeProcessing(){
        const beaconServer=serverCapableBrand()&&getCurrentSourceMode()==='server';
        const processBtn=document.getElementById('processBtn');
        if(!beaconServer) syncManualMapping();
        if(processBtn.disabled && !beaconServer) return;
        processBtn.disabled=true;
        processBtn.innerHTML='<i data-lucide="loader-circle" style="width:16px;"></i> Memproses...';
        lucide.createIcons();
        setProcessProgress('Menyiapkan pemrosesan data...');
        try{
            if(beaconServer){
                const vendorLabel=serverVendor()==='higertech'?'Higertech':serverVendor()==='tatonas'?'Tatonas':serverVendor()==='dashindo'?'Dashindo':'Beacon';
                const signature=currentServerRequestSignature();
                if(hasServerFetchResult && signature && signature===lastServerFetchSignature){
                    setProcessProgress('Menggunakan data '+vendorLabel+' yang sudah dimuat. Menyusun ulang hasil...');
                }else{
                    setProcessProgress('Mengambil data dari server '+vendorLabel+'...');
                    await fetchBeaconData();
                    setProcessProgress('Data diterima. Menyusun data jam-jaman...');
                }
            }else if(!rawData.length){
                throw new Error('Silakan upload file terlebih dahulu.');
            }else{
                setProcessProgress('Membaca dan menyusun data file...');
            }
            const ok=processLoadedData();
            if(ok===false)throw new Error('Pemrosesan data belum berhasil. Periksa format data.');
            setProcessProgress('Pemrosesan data selesai.','complete');
            hideProcessProgress(700);
        }catch(err){
            console.error(err);
            setBeaconStatus(err.message||String(err),false);
            showStatus(err.message||String(err),false);
            setProcessProgress(err.message||'Pemrosesan gagal.','error');
            hideProcessProgress(1400);
        }finally{
            const serverReady=serverCapableBrand()&&getCurrentSourceMode()==='server'&&!!document.getElementById('beaconParamSelect')?.value;
            const manualReady=!!(currentFile&&window.__autoTimeColumn&&window.__autoValueColumn);
            processBtn.disabled=(serverCapableBrand()&&getCurrentSourceMode()==='server')?!serverReady:!manualReady;
            processBtn.innerHTML='<i data-lucide="play" style="width:16px;"></i> Proses Data';
            lucide.createIcons();
        }
    }

    function correctionIsEnabled(){ const brand=document.getElementById('brandSelect').value; const id=(serverCapableBrand()&&getCurrentSourceMode()==='server')?'correctionEnabled':'manualCorrectionEnabled'; return document.getElementById(id)?.checked===true; }
    function getCorrectionValue(){ if(!correctionIsEnabled()) return document.getElementById('dataTypeSelect').value==='rain'?1:0; const dataType=document.getElementById('dataTypeSelect').value, manual=!serverCapableBrand()||getCurrentSourceMode()==='upload', id=manual?'manualCorrectionInput':'correctionInput', val=Number(document.getElementById(id)?.value); return Number.isFinite(val)?val:(dataType==='rain'?1:0); }
    function isPrimaryRainParameter(name){return /curah hujan|precipitation\s*intensity|precipitation|rainfall|rain intensity/i.test(String(name||''));}
    function isMainWaterParameter(name){return /water level|tinggi muka air|elevasi muka air|muka air|water stage|stage|elv\.?\s*ma/i.test(String(name||''));}
    function roundRainToPointTwo(value){return Math.round((value+Number.EPSILON)/0.2)*0.2;}
    function processLoadedData(){
        try{
            const dataType=document.getElementById('dataTypeSelect').value,selectedBrand=document.getElementById('brandSelect').value,brand=(serverCapableBrand()&&getCurrentSourceMode()==='server')?serverVendor():selectedBrand,timeCol=window.__autoTimeColumn,valueCol=window.__autoValueColumn,correctionVal=getCorrectionValue(),activeParam=getActiveParameterName(),rainAccumulation=dataType==='rain'&&isPrimaryRainParameter(activeParam),correctionEnabled=correctionIsEnabled(),requestedBounds=requestedTableDateBounds();
            if((!timeCol||!valueCol||timeCol===valueCol) && !(requestedBounds&&rawData.length===0)){showStatus('Kolom waktu atau nilai utama tidak dapat dikenali otomatis.',false);return false;}
            const hourlyBuckets={};let minISOKey=null,maxISOKey=null;
            const todayISOKey=getDateISOKey(new Date());
            rawData.forEach(row=>{const parsed=parseDateTimeStrict(row[timeCol],brand);if(!parsed)return;const {dateObj,hour}=parsed;let numVal=parseFloat(String(row[valueCol]).replace(/[^0-9.-]/g,''));if(isNaN(numVal))return;if(dataType==='rain')numVal*=correctionVal;else{if(brand==='tatonas'&&/water level|tinggi muka air|tma/i.test(String(valueCol)))numVal/=100;numVal+=correctionVal;}let effective=new Date(dateObj.getFullYear(),dateObj.getMonth(),dateObj.getDate());if(dataType==='rain'&&hour<7)effective.setDate(effective.getDate()-1);const key=getDateISOKey(effective);if(key>todayISOKey)return;if(!minISOKey||key<minISOKey)minISOKey=key;if(!maxISOKey||key>maxISOKey)maxISOKey=key;if(!hourlyBuckets[key])hourlyBuckets[key]={};if(!hourlyBuckets[key][hour])hourlyBuckets[key][hour]=[];hourlyBuckets[key][hour].push(numVal);});
            if(requestedBounds){minISOKey=requestedBounds[0];maxISOKey=requestedBounds[1];}
            if(maxISOKey&&maxISOKey>todayISOKey)maxISOKey=todayISOKey;
            if(!minISOKey||!maxISOKey||minISOKey>maxISOKey){showStatus('Tidak ada tanggal yang dapat diproses hingga hari ini.',false);return false;}
            const sortedDates=[];let curr=parseISOKeyToDate(minISOKey),end=parseISOKeyToDate(maxISOKey);while(curr<=end){sortedDates.push(getDateISOKey(curr));curr.setDate(curr.getDate()+1);}
            processedData=[];const hoursOrder=dataType==='rain'?HOURS_CH:HOURS_TMA;sortedDates.forEach(dKey=>{const rowPivot={'Tanggal':dKey};hoursOrder.forEach(h=>{const vals=(hourlyBuckets[dKey]||{})[h]||[];let val='';if(vals.length){let calc=rainAccumulation?vals.reduce((a,b)=>a+b,0):vals.reduce((a,b)=>a+b,0)/vals.length;if(dataType==='rain'&&correctionEnabled&&rainAccumulation)calc=roundRainToPointTwo(calc);val=parseFloat(calc.toFixed(rainAccumulation?1:2));}rowPivot[pad2(h)+':00']=val;});processedData.push(rowPivot);});
            renderPreviewTable();renderSummaryAndChart(dataType);document.getElementById('downloadBtn').disabled=false;document.getElementById('downloadCard').classList.add('active');cacheCurrentProcessingResult();saveProcessingState();showStatus('Pemrosesan data berhasil!',true);return true;
        }catch(err){console.error(err);showStatus('Terjadi kesalahan saat memproses data: '+err.message,false);return false;}
    }

    function renderPreviewTable() {
        const headerTr = document.getElementById('tableHeader');
        const bodyTbody = document.getElementById('tableBody');
        headerTr.innerHTML = '';
        bodyTbody.innerHTML = '';

        if (processedData.length === 0) return;

        const thNo = document.createElement('th');
        thNo.textContent = "No";
        headerTr.appendChild(thNo);

        const cols = Object.keys(processedData[0]);
        cols.forEach(col => {
            const th = document.createElement('th');
            th.textContent = col;
            headerTr.appendChild(th);
        });

        processedData.forEach((row, idx) => {
            const tr = document.createElement('tr');
            
            const tdNo = document.createElement('td');
            tdNo.textContent = idx + 1;
            tr.appendChild(tdNo);

            cols.forEach(col => {
                const td = document.createElement('td');
                const activeDataType=document.getElementById('dataTypeSelect')?.value;
                const isNumericValue=col!=='Tanggal' && row[col]!=='' && Number.isFinite(Number(row[col]));
                const isRainValue=activeDataType==='rain' && isPrimaryRainParameter(getActiveParameterName()) && isNumericValue;
                const isTmaValue=activeDataType==='tma' && isMainWaterParameter(getActiveParameterName()) && isNumericValue;
                td.textContent = isRainValue ? Number(row[col]).toFixed(1) : (isTmaValue ? Number(row[col]).toFixed(2) : row[col]);
                tr.appendChild(td);
            });
            bodyTbody.appendChild(tr);
        });

        document.getElementById('tableCard').style.display = 'block';
        const rowCount=document.getElementById('tableRowCount');
        if(rowCount) rowCount.textContent=`${processedData.length.toLocaleString('id-ID')} baris`;
    }

    function getActiveParameterName(){const serverMode=serverCapableBrand()&&getCurrentSourceMode()==='server';if(serverMode){const s=document.getElementById('beaconParamSelect');return s?.selectedOptions?.[0]?.textContent||'';}const s=document.getElementById('valueColumnSelect');return s?.selectedOptions?.[0]?.textContent||window.__autoValueColumn||'';}
    function getActiveStationLabel(dataType){
        if(!(serverCapableBrand()&&getCurrentSourceMode()==='server'))return '';
        let name=(document.getElementById('beaconPosSelect')?.selectedOptions?.[0]?.textContent||'').trim();
        name=name.replace(/^Pos\s+(?:ARR|AWLR|AWS)\s+/i,'').trim();
        if(!name)return '';
        if(/^Pos\s+/i.test(name))return name;
        return (dataType==='rain'?'Pos Curah Hujan ':'Pos Duga Air ')+name;
    }
    function updateSummaryLabels(dataType){
        document.getElementById('cardLastTitle').textContent='Data Terakhir';
        document.getElementById('cardMaxTitle').textContent='Tertinggi';
        document.getElementById('cardMinTitle').textContent='Terendah';
        document.getElementById('cardAggTitle').textContent=dataType==='rain'?'Akumulasi':'Rerata';
        const iconMap=dataType==='rain'
            ? {cardLastIcon:'gauge',cardMaxIcon:'activity',cardMinIcon:'droplets',cardAggIcon:'calculator'}
            : {cardLastIcon:'waves',cardMaxIcon:'trending-up',cardMinIcon:'trending-down',cardAggIcon:'sigma'};
        Object.entries(iconMap).forEach(([id,name])=>document.getElementById(id)?.setAttribute('data-lucide',name));
        const title=document.getElementById('summaryStatisticTitle');
        if(title) title.textContent=dataType==='rain'?'Ringkasan Curah Hujan':'Ringkasan Tinggi Muka Air';
        const info=document.getElementById('hydrologyInfoText');
        if(info) info.textContent=dataType==='rain'?'Curah hujan memakai hari hidrologis 07:00–06:59 WIB.':'Tinggi muka air mengikuti waktu pencatatan 00:00–23:59 WIB.';
        lucide.createIcons();
    }
    function getActiveUnit(dataType){const p=getActiveParameterName(),serverMode=serverCapableBrand()&&getCurrentSourceMode()==='server';if(serverMode){const opt=document.getElementById('beaconParamSelect')?.selectedOptions?.[0],meta=window.__activeServerParameter||window.__serverParameterMap?.[document.getElementById('beaconParamSelect')?.value];const unit=meta?.unit||opt?.dataset?.unit||'';if(unit)return unit;}if(/battery|baterai/i.test(p))return 'Volt';if(/humidity|kelembapan/i.test(p))return '%';if(/temperatur|temperature/i.test(p))return '°C';if(/pressure|tekanan udara/i.test(p))return 'mBar';if(/wind velocity|wind speed|kecepatan angin/i.test(p))return 'm/s';if(/wind direction|arah angin/i.test(p))return 'deg';if(/radiation|radiasi/i.test(p))return 'W/m²';if(/uv/i.test(p))return 'Index';if(/pan level/i.test(p))return 'mm';if(/debit|discharge|flow rate|streamflow/i.test(p))return 'm³/det';if(isMainWaterParameter(p))return 'm';return dataType==='rain'?'mm':'m';}
    function actualTimestampLabel(rowDate,hour,dataType){const m=String(rowDate).match(/^(\d{4})-(\d{2})-(\d{2})$/);if(!m)return `${rowDate} ${pad2(hour)}:00`;const d=new Date(Number(m[1]),Number(m[2])-1,Number(m[3]));if(dataType==='rain'&&hour<7)d.setDate(d.getDate()+1);return `${getDateISOKey(d)} ${pad2(hour)}:00`;}
    function summaryPeriodLabel(){
        if(!processedData.length)return '-';
        const first=String(processedData[0]?.Tanggal||'-');
        const last=String(processedData.at(-1)?.Tanggal||first);
        return `${first} s.d. ${last}`;
    }
    function renderSummaryAndChart(dataType){
        document.getElementById('summaryGrid').style.display='grid';document.getElementById('chartCard').style.display='block';
        let allValues=[],timeLabels=[],chartSeriesData=[];
        processedData.forEach(row=>{Object.keys(row).forEach(k=>{if(k.includes(':00')&&row[k]!==''&&row[k]!==undefined){const val=parseFloat(row[k]);if(!isNaN(val)){allValues.push(val);timeLabels.push(actualTimestampLabel(row.Tanggal,parseInt(k.slice(0,2),10),dataType));chartSeriesData.push(val);}}});});
        const unit=getActiveUnit(dataType),p=getActiveParameterName(),station=getActiveStationLabel(dataType),primaryRain=dataType==='rain'&&isPrimaryRainParameter(p),baseTitle=primaryRain?'Grafik Jam-Jaman Curah Hujan':(dataType==='tma'&&isMainWaterParameter(p)?'Grafik Tinggi Muka Air Jam-Jaman':`Grafik Jam-Jaman ${p||'Data'}`);
        // Satuan statistik mengikuti makna hidrologinya: ekstrem hujan jam-jaman
        // dinyatakan sebagai intensitas (mm/jam), sedangkan data terakhir dan
        // akumulasi tetap memakai satuan parameter asal (mm).
        const summaryUnits={
            unitLast:unit,
            unitMax:primaryRain?'mm/jam':unit,
            unitMin:primaryRain?'mm/jam':unit,
            unitAgg:unit,
        };
        Object.entries(summaryUnits).forEach(([id,value])=>{const el=document.getElementById(id);if(el)el.textContent=value;});
        updateSummaryLabels(dataType);document.getElementById('chartTitle').textContent=station?`${baseTitle} — ${station}`:baseTitle;
        document.getElementById('chartSub').textContent = [p || (dataType==='rain' ? 'Curah Hujan' : 'Tinggi Muka Air'), summaryPeriodLabel()].filter(Boolean).join('  ');
        ['cardLastVal','cardMaxVal','cardMinVal','cardAggVal'].forEach(id=>document.getElementById(id).textContent='-');document.getElementById('cardLastDate').textContent='-';document.getElementById('subtextMax').textContent='-';document.getElementById('subtextMin').textContent='-';document.getElementById('subtextAgg').textContent=summaryPeriodLabel();
        if(allValues.length){
            const lastVal=chartSeriesData.at(-1),maxVal=Math.max(...allValues),minVal=Math.min(...allValues),maxIdx=allValues.indexOf(maxVal),minIdx=allValues.indexOf(minVal),aggregate=dataType==='rain'?allValues.reduce((a,b)=>a+b,0):allValues.reduce((a,b)=>a+b,0)/allValues.length;
            const summaryPrecision=primaryRain?1:2;
            document.getElementById('cardLastVal').textContent=lastVal.toFixed(summaryPrecision);document.getElementById('cardMaxVal').textContent=maxVal.toFixed(summaryPrecision);document.getElementById('cardMinVal').textContent=minVal.toFixed(summaryPrecision);document.getElementById('cardAggVal').textContent=aggregate.toFixed(summaryPrecision);document.getElementById('cardLastDate').textContent=timeLabels.at(-1);document.getElementById('subtextMax').textContent=timeLabels[maxIdx];document.getElementById('subtextMin').textContent=timeLabels[minIdx];document.getElementById('subtextAgg').textContent=summaryPeriodLabel();
        }
        window.__chartState = {dataType, unit, parameter:p, station, primaryRain, title:document.getElementById('chartTitle').textContent, subtitle:document.getElementById('chartSub').textContent, labels:timeLabels, values:chartSeriesData};
        updateProcessingReferenceSummary();
        setProcessingResultState(true);
        setTimeout(()=>renderTelemetryChart(window.__chartState),40);
    }

    function renderTelemetryChart(state){
        const canvas=document.getElementById('tmaChart');
        if(!canvas || !window.Chart || !state) return;
        if(tmaChartInstance){
            tmaChartInstance.destroy();
            tmaChartInstance=null;
        }

        const isDark=document.documentElement.getAttribute('data-theme')==='dark';
        const lineColor=isDark?'#B7C8EE':'#223468';
        const textColor=isDark?'#C8D1E1':'#596579';
        const gridColor=isDark?'rgba(183,200,238,.18)':'rgba(34,52,104,.14)';
        const tooltipBg=isDark?'#0F172A':'#FFFFFF';
        const tooltipText=isDark?'#F8FAFC':'#0F172A';
        const parameterLabel=state.parameter||(state.dataType==='rain'?'Curah Hujan':'Tinggi Muka Air');

        const rainChart=state.dataType==='rain';
        const dataset=rainChart?{
            label:`${parameterLabel} (${state.unit})`,
            data:state.values,
            borderColor:lineColor,
            backgroundColor:lineColor,
            borderWidth:1,
            borderRadius:2,
            borderSkipped:false
        }:{
            label:`${parameterLabel} (${state.unit})`,
            data:state.values,
            borderColor:lineColor,
            backgroundColor:lineColor,
            borderWidth:2.4,
            pointRadius:0,
            pointHoverRadius:4,
            pointHitRadius:10,
            pointBorderWidth:0,
            tension:.22,
            fill:false,
            spanGaps:false
        };

        tmaChartInstance=new Chart(canvas.getContext('2d'),{
            type:rainChart?'bar':'line',
            data:{
                labels:state.labels,
                datasets:[dataset]
            },
            options:{
                responsive:true,
                maintainAspectRatio:false,
                animation:{duration:260},
                interaction:{mode:'index',intersect:false},
                plugins:{
                    legend:{display:false},
                    title:{display:false},
                    tooltip:{
                        backgroundColor:tooltipBg,
                        titleColor:tooltipText,
                        bodyColor:tooltipText,
                        borderColor:gridColor,
                        borderWidth:1,
                        padding:10,
                        displayColors:false,
                        callbacks:{
                            label:(ctx)=>`${parameterLabel}: ${Number(ctx.parsed.y).toFixed(state.primaryRain?1:2)} ${state.unit}`
                        }
                    }
                },
                scales:{
                    x:{
                        grid:{display:false},
                        border:{color:gridColor},
                        ticks:{color:textColor,maxRotation:0,autoSkip:true,maxTicksLimit:8,font:{size:10}},
                        title:{display:true,text:'Waktu',color:textColor,font:{size:11,weight:'600'}}
                    },
                    y:{
                        beginAtZero:!!state.primaryRain,
                        grid:{color:gridColor,drawTicks:false},
                        border:{display:false},
                        ticks:{color:textColor,padding:8,font:{size:10},callback:(value)=>Number(value).toFixed(rainChart?1:2)},
                        title:{display:true,text:`${parameterLabel} (${state.unit})`,color:textColor,font:{size:11,weight:'600'}}
                    }
                }
            }
        });
        bindChartExportMenu();
    }

    function getChartExportMeta(){
        const title = document.getElementById('chartTitle')?.textContent?.trim() || 'Grafik Telemetri';
        const subtitle = document.getElementById('chartSub')?.textContent?.trim() || summaryPeriodLabel();
        return {title, subtitle};
    }

    function chartImageDataUrl(kind='png'){
        const source=document.getElementById('tmaChart');
        if(!source || !tmaChartInstance) return '';
        const mime=kind==='jpeg'?'image/jpeg':'image/png';
        const meta=getChartExportMeta();
        const scale=Math.max(1, source.width / Math.max(1, source.clientWidth || source.width));
        const headerHeight=Math.round(82*scale);
        const out=document.createElement('canvas');
        out.width=source.width;
        out.height=source.height+headerHeight;
        const ctx=out.getContext('2d');
        const isDark=document.documentElement.getAttribute('data-theme')==='dark';
        const bg=isDark?'#182236':'#FFFFFF';
        const titleColor=isDark?'#EDF1F8':'#223468';
        const subColor=isDark?'#AAB4C7':'#667085';
        ctx.fillStyle=bg;
        ctx.fillRect(0,0,out.width,out.height);
        const left=Math.round(18*scale);
        const top=Math.round(19*scale);
        ctx.fillStyle='#FCB717';
        ctx.fillRect(left,top,Math.round(34*scale),Math.max(3,Math.round(3*scale)));
        ctx.fillStyle=titleColor;
        ctx.font=`700 ${Math.round(15*scale)}px "Plus Jakarta Sans", Arial, sans-serif`;
        ctx.textBaseline='top';
        ctx.fillText(meta.title,left,top+Math.round(12*scale),out.width-left*2);
        ctx.fillStyle=subColor;
        ctx.font=`500 ${Math.round(10*scale)}px "Plus Jakarta Sans", Arial, sans-serif`;
        ctx.fillText(meta.subtitle,left,top+Math.round(36*scale),out.width-left*2);
        ctx.drawImage(source,0,headerHeight);
        return out.toDataURL(mime,kind==='jpeg'?.94:1);
    }

    async function triggerChartDownload(kind){
        if(kind === 'xls'){ exportToExcel(); return; }
        if(!tmaChartInstance) return;
        const meta=getChartExportMeta();
        const filename=(meta.title||'grafik').replace(/[^a-z0-9]+/gi,' ').trim()||'grafik';
        const imageKind=kind==='jpeg'?'jpeg':'png';
        const dataUrl=chartImageDataUrl(imageKind);
        if(!dataUrl) return;
        if(kind === 'print'){
            const w=window.open('', '_blank');
            if(!w) return;
            w.document.write(`<html><head><title>${meta.title}</title><style>body{margin:0;padding:24px;background:#fff}img{display:block;max-width:100%;height:auto;margin:auto}</style></head><body><img src="${dataUrl}" onload="window.print();setTimeout(function(){window.close();},250)"></body></html>`);
            w.document.close();
            return;
        }
        const a=document.createElement('a');
        a.href=dataUrl;
        a.download=`${filename}.${imageKind==='jpeg'?'jpg':'png'}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    function bindChartExportMenu(){
        const btn = document.getElementById('chartMenuBtn');
        const menu = document.getElementById('chartExportMenu');
        if(!btn || !menu || btn.dataset.bound === '1') return;
        btn.dataset.bound = '1';
        const closeMenu = ()=>{ menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
        btn.addEventListener('click', (event)=>{
            event.stopPropagation();
            menu.hidden = !menu.hidden;
            btn.setAttribute('aria-expanded', String(!menu.hidden));
        });
        menu.addEventListener('click', async (event)=>{
            const action = event.target.closest('button')?.dataset?.chartAction;
            if(!action) return;
            closeMenu();
            await triggerChartDownload(action);
        });
        document.addEventListener('click', (event)=>{
            if(menu.hidden) return;
            if(!menu.contains(event.target) && !btn.contains(event.target)) closeMenu();
        });
    }


    function setProcessingResultState(hasResults){
        const empty=document.getElementById('processingResultEmpty');
        if(empty) empty.hidden=!!hasResults;
    }

    function referencePeriodLabel(){
        if(processedData.length) return summaryPeriodLabel();
        const mode=document.getElementById('beaconPeriodMode')?.value || '';
        if(mode==='day') return document.getElementById('beaconDailyDate')?.value || 'Belum dipilih';
        if(mode==='month') return document.getElementById('beaconMonthYearPicker')?.value || 'Belum dipilih';
        if(mode==='year') return document.getElementById('beaconYearPicker')?.value || 'Belum dipilih';
        if(mode==='custom'){
            const from=document.getElementById('beaconCustomFrom')?.value || '';
            const to=document.getElementById('beaconCustomTo')?.value || '';
            return from&&to ? `${from} s.d. ${to}` : 'Belum dipilih';
        }
        return 'Belum diproses';
    }

    function updateProcessingReferenceSummary(){
        const dataType=document.getElementById('dataTypeSelect')?.value || 'rain';
        const sourceMode=getCurrentSourceMode();
        const brand=document.getElementById('brandSelect');
        const vendorNames={all:'Semua',beacon:'Beacon',tatonas:'Tatonas',higertech:'Higertech',dashindo:'Dashindo'};
        let logger=vendorNames[brand?.value] || brand?.selectedOptions?.[0]?.textContent || '-';
        if(sourceMode==='server' && brand?.value==='all' && document.getElementById('beaconPosSelect')?.value){
            logger=vendorNames[selectedServerVendor()] || selectedServerVendor();
        }
        if(sourceMode==='upload') logger=`${logger} Upload`;

        let station='-';
        let parameter='-';
        if(sourceMode==='server'){
            station=(document.getElementById('beaconPosSelect')?.selectedOptions?.[0]?.textContent || '-').trim();
            parameter=(document.getElementById('beaconParamSelect')?.selectedOptions?.[0]?.textContent || '-').trim();
        }else{
            station=currentFileName ? currentFileName.replace(/\.[^.]+$/,'') : 'File manual';
            parameter=(document.getElementById('valueColumnSelect')?.selectedOptions?.[0]?.textContent || window.__autoValueColumn || '-').trim();
        }
        if(/memuat|pilih pos|tidak ada|gagal/i.test(station)) station='-';
        if(/memuat|pilih pos|tidak ada|gagal/i.test(parameter)) parameter='-';

        const loggerEl=document.getElementById('summaryLogger');
        const stationEl=document.getElementById('summaryStation');
        const parameterEl=document.getElementById('summaryParameter');
        const typeEl=document.getElementById('summaryDataType');
        const rangeEl=document.getElementById('summaryRange');
        const periodBadge=document.querySelector('#chartPeriodBadge span');
        if(loggerEl) loggerEl.textContent=logger;
        if(stationEl) stationEl.textContent=station;
        if(parameterEl) parameterEl.textContent=parameter;
        if(typeEl) typeEl.textContent='Jam-Jaman';
        const period=referencePeriodLabel();
        if(rangeEl) rangeEl.textContent=processedData.length ? period : (period==='Belum dipilih'?'Belum diproses':period);
        if(periodBadge) periodBadge.textContent=processedData.length ? period : 'Seluruh periode';
        updateSummaryLabels(dataType);
        lucide.createIcons();
    }

    function exportToExcel() {
        if (processedData.length === 0) return;

        const excelData = processedData.map(row => {
            const newRow = { ...row };
            const match = String(newRow["Tanggal"] || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
            if (match) {
                newRow["Tanggal"] = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
            }
            return newRow;
        });

        const ws = XLSX.utils.json_to_sheet(excelData, { cellDates: true });

        const range = XLSX.utils.decode_range(ws['!ref']);
        const exportDataType=document.getElementById('dataTypeSelect')?.value;
        const exportIsRain=exportDataType==='rain' && isPrimaryRainParameter(getActiveParameterName());
        const exportIsTma=exportDataType==='tma' && isMainWaterParameter(getActiveParameterName());
        for (let R = range.s.r + 1; R <= range.e.r; ++R) {
            const cellAddress = XLSX.utils.encode_cell({ r: R, c: 0 });
            if (ws[cellAddress] && ws[cellAddress].t === 'd') {
                ws[cellAddress].z = 'yyyy-mm-dd';
            }
            if(exportIsRain || exportIsTma){
                for(let C=1; C<=range.e.c; C++){
                    const valueAddress=XLSX.utils.encode_cell({r:R,c:C});
                    if(ws[valueAddress] && ws[valueAddress].t==='n') ws[valueAddress].z=exportIsRain?'0.0':'0.00';
                }
            }
        }

        ws['!cols'] = [{ wch: 12 }];

        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, "Hasil Pivot");

        const dataTypeSelect = document.getElementById('dataTypeSelect');
        const dataTypeName = dataTypeSelect.options[dataTypeSelect.selectedIndex].text;
        
        const brandSelect = document.getElementById('brandSelect');
        const vendorNames={beacon:'Beacon',tatonas:'Tatonas',higertech:'Higertech',dashindo:'Dashindo'};
        const brandName = brandSelect.value==='all' && getCurrentSourceMode()==='server' ? (vendorNames[serverVendor()]||'Semua') : brandSelect.options[brandSelect.selectedIndex].text;

        const baseName = String(currentFileName || 'Data').replace(/\s+\d{2}:\d{2}(?::\d{2})?/g,'').replace(/\s{2,}/g,' ').trim();
        const exportFileName = `Pivot Data ${dataTypeName} ${brandName} ${baseName}.xlsx`;

        XLSX.writeFile(wb, exportFileName);
    }

    function applySavedProcessingControls(state){
        if(!state) return;
        const setIfOption=(id,value)=>{const el=document.getElementById(id);if(el&&value!==undefined&&value!==null&&[...el.options].some(o=>o.value===String(value)))el.value=String(value);};
        setIfOption('brandSelect',state.brand);
        setIfOption('dataTypeSelect',state.dataType);
        setIfOption('beaconPeriodMode',state.periodMode);
        const direct={beaconDailyDate:'dailyDate',beaconMonthYearPicker:'monthPicker',beaconMonth:'month',beaconMonthYear:'monthYear',beaconYearPicker:'yearPicker',beaconYear:'year',beaconCustomFrom:'customFrom',beaconCustomTo:'customTo'};
        Object.entries(direct).forEach(([id,key])=>{const el=document.getElementById(id);if(el&&state[key])el.value=state[key];});
        const ce=document.getElementById('correctionEnabled');
        const ci=document.getElementById('correctionInput');
        if(ce)ce.checked=!!state.correctionEnabled;
        if(ci&&state.correctionValue!=='')ci.value=state.correctionValue;
        if(window.jQuery&&jQuery.fn?.datepicker){
            const parseDay=value=>{const m=String(value||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);return m?new Date(Number(m[1]),Number(m[2])-1,Number(m[3])):null;};
            const safeSet=(id,date)=>{if(!date)return;try{jQuery('#'+id).datepicker('setDate',date);}catch(_err){}};
            safeSet('beaconDailyDate',parseDay(state.dailyDate));
            safeSet('beaconCustomFrom',parseDay(state.customFrom));
            safeSet('beaconCustomTo',parseDay(state.customTo));
            if(state.month&&state.monthYear)safeSet('beaconMonthYearPicker',new Date(Number(state.monthYear),Number(state.month)-1,1));
            if(state.year)safeSet('beaconYearPicker',new Date(Number(state.year),0,1));
        }
        onBeaconPeriodModeChange();
        updateCorrectionUI();
    }

    document.addEventListener('hydro:authchange', ()=>updateSourceConnectionIndicator());
    document.getElementById('beaconPosSelect').addEventListener('change', async ()=>{await loadBeaconParameters();saveProcessingState();});
    document.getElementById('beaconParamSelect').addEventListener('change', ()=>{ const sel=document.getElementById('beaconParamSelect');window.__activeServerParameter=window.__serverParameterMap?.[sel.value]||null;updateSummaryLabels(document.getElementById('dataTypeSelect').value); updateSourceVisibility(); saveProcessingState(); });
    document.getElementById('beaconPeriodMode').addEventListener('change', onBeaconPeriodModeChange);
    document.getElementById('sourceModeSelect').addEventListener('change', ()=>{ setSourceMode(document.getElementById('sourceModeSelect').value); });
    document.getElementById('timeColumnSelect').addEventListener('change', syncManualMapping);
    document.getElementById('valueColumnSelect').addEventListener('change', syncManualMapping);
    populateBeaconMonths();
    bindCorrectionToggles();
    bindChartExportMenu();
    setProcessingResultState(false);
    updateProcessingReferenceSummary();
    ['brandSelect','dataTypeSelect','sourceModeSelect','beaconPosSelect','beaconParamSelect','beaconPeriodMode','beaconDailyDate','beaconMonthYearPicker','beaconYearPicker','beaconCustomFrom','beaconCustomTo','timeColumnSelect','valueColumnSelect'].forEach(id=>{
        const el=document.getElementById(id);
        if(!el) return;
        el.addEventListener('change',()=>{if(processingStateReady)saveProcessingState();setTimeout(updateProcessingReferenceSummary,0);});
        el.addEventListener('input',()=>{if(processingStateReady)saveProcessingState();setTimeout(updateProcessingReferenceSummary,0);});
    });
    (async function initializeProcessingPage(){
        const brandSelect=document.getElementById('brandSelect');
        const typeSelect=document.getElementById('dataTypeSelect');
        const saved=readProcessingState();
        if(brandSelect) brandSelect.value=saved?.brand||'all';
        if(typeSelect) typeSelect.value=saved?.dataType||'tma';
        applySavedProcessingControls(saved);
        updateSummaryLabels(typeSelect?.value||'tma');
        updateCorrectionUI();

        // Terapkan mode sumber sebelum request /api/auth/status agar halaman tidak
        // sempat merender area Upload Manual ketika sesi Flask sudah terautentikasi.
        // Jika belum login, tampilkan mode manual segera tanpa menunggu request.
        const sourceSelect=document.getElementById('sourceModeSelect');
        const hidden=document.getElementById('beaconSourceMode');
        const bootstrapAuthenticated=!!window.HydroUI?.authState?.authenticated;
        const initialSource=bootstrapAuthenticated
            ? (saved?.sourceMode==='upload'?'upload':'server')
            : 'upload';
        if(sourceSelect) sourceSelect.value=initialSource;
        if(hidden) hidden.value=initialSource;
        updateSourceVisibility();

        const authenticated=await checkTelemetryAuth();
        if(authenticated){
            const wantedSource=saved?.sourceMode==='upload'?'upload':'server';
            if(sourceSelect) sourceSelect.value=wantedSource;
            if(hidden) hidden.value=wantedSource;
            updateSourceVisibility();
            if(wantedSource==='server'){
                const dataType=typeSelect?.value||'tma';
                if(saved?.position){
                    await loadBeaconPositions(dataType,saved.position,{parameterId:saved.parameter||''});
                }else if((brandSelect?.value||'all')==='all' && dataType==='tma'){
                    const fastReady=await loadInitialKrangganFast();
                    if(fastReady){
                        const keepPosition=document.getElementById('beaconPosSelect')?.value||'';
                        setTimeout(()=>loadBeaconPositions('tma',keepPosition,{silent:true}).catch(()=>{}),500);
                    }else{
                        await loadBeaconPositions(dataType);
                    }
                }else{
                    await loadBeaconPositions(dataType);
                }
                // Saat kembali dari Monitoring, pilihan terakhir sudah dipulihkan.
                // Jika kombinasi logger/pos/parameter/periode/koreksi sama, hasil
                // olahan ikut dikembalikan tanpa menekan Proses Data dan tanpa request.
                restoreProcessingResultFromCache({announce:true});
            }
        }else{
            updateSourceVisibility();
            if(window.HydroUI?.authState?.configured!==false) setTimeout(()=>openTelemetryAuth(),80);
        }
        processingStateReady=true;
        if(authenticated) saveProcessingState();
        setTimeout(updateProcessingReferenceSummary,0);
    })();
