import {computeUValue} from './engine/thermal.js';
import {saturationPressurePa} from './engine/psychrometrics.js';
import {parseEpw} from './climate/epw.js';
import {runMonthlyMode} from './modes/monthly.js';
import {runQuasiHourlyMode} from './modes/quasiHourly.js';
import {REFERENCE_LAYERS, KLAGENFURT_REFERENCE_MONTHLY, MONTH_NAMES} from './data/reference.js';
import {parseMaterialLibrary, searchMaterials} from './data/materialLibrary.js';
import {lineChart} from './charts/svgCharts.js';

const clone = value => JSON.parse(JSON.stringify(value));

export class App {
  constructor(root) {
    this.root=root;
    this.state={
      mode:'monthly', layers:clone(REFERENCE_LAYERS), monthly:clone(KLAGENFURT_REFERENCE_MONTHLY),
      rsi:0.25,rse:0.04, indoor:{ti_C:22,rhi:0.5}, epw:null, materials:[], materialQuery:'', muPolicy:'dry',
      result:null,error:null, selectedStep:11,
    };
  }

  mount(){ this.render(); this.calculate(); }
  set(patch, recalc=false){Object.assign(this.state,patch);this.render();if(recalc)this.calculate();}

  calculate(){
    try{
      const {layers,mode,rsi,rse}=this.state;
      if(!layers.length) throw new Error('Add at least one layer.');
      let result;
      if(mode==='monthly') result=runMonthlyMode({layers,rows:this.state.monthly,rsi,rse});
      else {
        if(!this.state.epw) throw new Error('Upload an EPW file for quasi-hourly mode.');
        result=runQuasiHourlyMode({layers,epwRecords:this.state.epw.records,indoor:this.state.indoor,rsi,rse});
      }
      this.state.result=result;this.state.error=null;
    } catch(e){this.state.result=null;this.state.error=e?.message??String(e);}
    this.renderResults();
  }

  render(){
    this.root.innerHTML=`
      <header class="app-header"><div><div class="kicker">BUILDING ENERGY TOOLS</div><h1>Building Envelope Studio</h1><p>U-value · Glaser condensation · climate-driven assessment</p></div><div class="header-side"><span class="badge">alpha 0.1</span></div></header>
      <main class="app-shell">
        <section class="modebar">
          <button data-mode="monthly" class="mode ${this.state.mode==='monthly'?'active':''}">Monthly normative candidate</button>
          <button data-mode="hourly" class="mode ${this.state.mode==='hourly'?'active':''}">Quasi-hourly EPW</button>
          <span class="method-note">Steady heat + vapour diffusion. No transient moisture storage/sorption/capillary transport.</span>
        </section>
        <div class="workspace">
          <aside class="panel inputs"><div class="panel-head"><h2>Construction</h2><button id="resetBtn" class="ghost">Reset</button></div>
            <div id="layerList" class="layers"></div>
            <button id="addLayerBtn" class="wide">+ Add layer</button>
            <details class="library"><summary>Material library</summary>
              <div class="library-body"><label>Import library JSON<input id="libraryFile" type="file" accept="application/json,.json"></label><label>Search<input id="materialSearch" value="${escapeHtml(this.state.materialQuery)}" placeholder="mineral wool, concrete…"></label><div id="materialResults" class="material-results"></div></div>
            </details>
          </aside>
          <section class="main-column">
            <section class="panel climate"><div class="panel-head"><h2>Boundary conditions</h2></div><div id="climateControls"></div></section>
            <section class="kpis" id="kpis"></section>
            <section class="chart-grid">
              <article class="panel chart-card"><div class="chart-title"><b>I · Vapour pressure</b><span>p(T), pᵥ</span></div><div id="chart1"></div></article>
              <article class="panel chart-card"><div class="chart-title"><b>II · Diffusion</b><span>s<sub>d</sub> coordinate</span></div><div id="chart2"></div></article>
              <article class="panel chart-card"><div class="chart-title"><b>III · Temperature</b><span>ΣR coordinate</span></div><div id="chart3"></div></article>
              <article class="panel chart-card"><div class="chart-title"><b>IV · Moisture balance</b><span>stored condensate</span></div><div id="chart4"></div></article>
            </section>
          </section>
        </div>
      </main>`;
    this.bind(); this.renderLayers(); this.renderClimate(); this.renderMaterialResults(); this.renderResults();
  }

  bind(){
    this.root.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>this.set({mode:b.dataset.mode},true)));
    this.root.querySelector('#resetBtn').onclick=()=>this.set({layers:clone(REFERENCE_LAYERS)},true);
    this.root.querySelector('#addLayerBtn').onclick=()=>{this.state.layers.push({id:crypto.randomUUID(),name:'New layer',thickness_m:0.1,lambda_W_mK:0.04,mu:5});this.render();this.calculate();};
    this.root.querySelector('#libraryFile').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;try{const lib=parseMaterialLibrary(await f.text(),{muPolicy:this.state.muPolicy});this.state.materials=lib.materials;this.state.materialQuery='';this.render();}catch(err){alert(err.message);}};
    this.root.querySelector('#materialSearch').oninput=e=>{this.state.materialQuery=e.target.value;this.renderMaterialResults();};
  }

  renderLayers(){
    const host=this.root.querySelector('#layerList');host.replaceChildren();
    this.state.layers.forEach((layer,i)=>{
      const row=document.createElement('div');row.className='layer-row';row.innerHTML=`
        <div class="layer-top"><span class="layer-index">${i+1}</span><input data-k="name" value="${escapeHtml(layer.name)}"><div class="layer-actions"><button data-act="up" title="Move up">↑</button><button data-act="down" title="Move down">↓</button><button data-act="del" title="Delete">×</button></div></div>
        <div class="layer-fields"><label>d <input data-k="thickness_mm" type="number" step="1" value="${fmt(layer.thickness_m*1000,1)}"><em>mm</em></label><label>λ <input data-k="lambda_W_mK" type="number" step="0.001" value="${layer.lambda_W_mK}"><em>W/mK</em></label><label>μ <input data-k="mu" type="number" step="0.1" value="${layer.mu??''}"><em>–</em></label></div>`;
      row.querySelectorAll('input').forEach(input=>input.onchange=()=>{const k=input.dataset.k;if(k==='name')layer.name=input.value;else if(k==='thickness_mm')layer.thickness_m=Number(input.value)/1000;else layer[k]=Number(input.value);this.calculate();});
      row.querySelector('[data-act="up"]').onclick=()=>this.moveLayer(i,-1);row.querySelector('[data-act="down"]').onclick=()=>this.moveLayer(i,1);row.querySelector('[data-act="del"]').onclick=()=>{this.state.layers.splice(i,1);this.render();this.calculate();};
      host.append(row);
    });
  }
  moveLayer(i,d){const j=i+d;if(j<0||j>=this.state.layers.length)return;[this.state.layers[i],this.state.layers[j]]=[this.state.layers[j],this.state.layers[i]];this.render();this.calculate();}

  renderClimate(){
    const host=this.root.querySelector('#climateControls');
    if(this.state.mode==='monthly'){
      host.innerHTML=`<div class="monthly-head"><span>Month</span><span>Tₑ °C</span><span>RHₑ %</span><span>Tᵢ °C</span><span>RHᵢ %</span></div><div class="monthly-grid">${this.state.monthly.map((r,i)=>`<div class="month-row"><b>${MONTH_NAMES[i]}</b><input data-m="${i}" data-k="te_C" value="${r.te_C}"><input data-m="${i}" data-k="rhe" value="${fmt(r.rhe*100,1)}"><input data-m="${i}" data-k="ti_C" value="${r.ti_C}"><input data-m="${i}" data-k="rhi" value="${fmt(r.rhi*100,1)}"></div>`).join('')}</div><p class="note">Initial values reproduce the climate/indoor-condition table from the supplied Excel workbook. Normative climate presets will be audited separately.</p>`;
      host.querySelectorAll('input').forEach(inp=>inp.onchange=()=>{const r=this.state.monthly[Number(inp.dataset.m)],k=inp.dataset.k;const v=Number(inp.value);r[k]=(k==='rhe'||k==='rhi')?v/100:v;this.calculate();});
    }else{
      host.innerHTML=`<div class="hourly-controls"><label>EPW file<input id="epwFile" type="file" accept=".epw,text/plain"></label><label>Indoor temperature<input id="tiHourly" type="number" value="${this.state.indoor.ti_C}" step="0.5"><em>°C</em></label><label>Indoor RH<input id="rhiHourly" type="number" value="${this.state.indoor.rhi*100}" step="1"><em>%</em></label></div><div class="epw-status">${this.state.epw?`Loaded: <b>${escapeHtml(this.state.epw.meta.city||'EPW')}</b> · ${this.state.epw.records.length} records`:'No EPW loaded.'}</div><p class="note">Each EPW hour is solved as an independent steady state while condensate mass is carried forward. This is intentionally not EN 15026 transient hygrothermal simulation.</p>`;
      host.querySelector('#epwFile').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;try{this.state.epw=parseEpw(await f.text());this.render();this.calculate();}catch(err){alert(err.message);}};
      host.querySelector('#tiHourly').onchange=e=>{this.state.indoor.ti_C=Number(e.target.value);this.calculate();};
      host.querySelector('#rhiHourly').onchange=e=>{this.state.indoor.rhi=Number(e.target.value)/100;this.calculate();};
    }
  }

  renderMaterialResults(){
    const host=this.root.querySelector('#materialResults');if(!host)return;
    if(!this.state.materials.length){host.innerHTML='<p class="empty">Import the supplied material library JSON to search the full catalogue.</p>';return;}
    const items=searchMaterials(this.state.materials,this.state.materialQuery,40);host.innerHTML='';items.forEach(m=>{const b=document.createElement('button');b.className='material-item';b.disabled=!m.hasMoistureData;b.innerHTML=`<b>${escapeHtml(m.name)}</b><span>λ ${fmt(m.lambda_W_mK,3)} W/mK · μ ${m.mu==null?'—':fmt(m.mu,1)}</span>`;b.onclick=()=>{this.state.layers.push({id:m.id,name:m.name,thickness_m:0.1,lambda_W_mK:m.lambda_W_mK,mu:m.mu,source:m.source});this.render();this.calculate();};host.append(b);});
  }

  renderResults(){
    const kpis=this.root.querySelector('#kpis');if(!kpis)return;
    if(this.state.error){kpis.innerHTML=`<article class="kpi error"><span>Calculation</span><b>${escapeHtml(this.state.error)}</b></article>`;['chart1','chart2','chart3','chart4'].forEach(id=>this.root.querySelector('#'+id)?.replaceChildren());return;}
    if(!this.state.result)return;
    const u=computeUValue(this.state.layers,{rsi:this.state.rsi,rse:this.state.rse});
    const results=this.state.result.results;const maxMoist=Math.max(0,...results.map(r=>r.totalStored_kg_m2));const endMoist=results.at(-1)?.totalStored_kg_m2??0;const totalSd=u.layers.reduce((s,l)=>s+l.sd_m,0);
    kpis.innerHTML=`${kpi('U-value',fmt(u.U_W_m2K,3),'W/m²K')}${kpi('R total',fmt(u.totalR_m2K_W,3),'m²K/W')}${kpi('Σsd',fmt(totalSd,2),'m')}${kpi('Max condensate',fmt(maxMoist*1000,1),'g/m²')}${kpi('End condensate',fmt(endMoist*1000,1),'g/m²')}`;
    const idx=Math.min(this.state.selectedStep,results.length-1);const r=results[Math.max(0,idx)];this.drawCharts(r,results);
  }

  drawCharts(r,results){
    if(!r)return;
    const temps=r.diffusionNodes.map(n=>n.T_C);const tmin=Math.min(...temps)-4,tmax=Math.max(...temps)+4;const tPoints=[];for(let t=tmin;t<=tmax;t+=(tmax-tmin)/60)tPoints.push({x:t,y:saturationPressurePa(t)});
    lineChart(this.root.querySelector('#chart1'),[{name:'p_sat(T)',points:tPoints},{name:'current states',points:r.diffusionNodes.map((n,i)=>({x:n.T_C,y:r.profile.p_Pa[i]}))}],{xLabel:'Temperature [°C]',yLabel:'Pressure [Pa]'});
    lineChart(this.root.querySelector('#chart2'),[{name:'p_sat',points:r.diffusionNodes.map(n=>({x:n.sd_m,y:n.psat_Pa}))},{name:'p_v',points:r.diffusionNodes.map((n,i)=>({x:n.sd_m,y:r.profile.p_Pa[i]}))}],{xLabel:'Σsd [m]',yLabel:'Pressure [Pa]',xDomain:[0,r.diffusionNodes.at(-1).sd_m]});
    lineChart(this.root.querySelector('#chart3'),[{name:'T',points:r.thermal.nodes.map(n=>({x:n.Rcum,y:n.T_C}))}],{xLabel:'ΣR [m²K/W]',yLabel:'Temperature [°C]',xDomain:[0,r.thermal.totalR_m2K_W]});
    lineChart(this.root.querySelector('#chart4'),[{name:'stored condensate',points:results.map((x,i)=>({x:i+1,y:x.totalStored_kg_m2*1000}))}],{xLabel:this.state.mode==='monthly'?'Month':'Hour',yLabel:'g/m²',xDomain:[1,Math.max(2,results.length)]});
  }
}

function fmt(v,n=2){return Number(v).toFixed(n)}
function kpi(name,value,unit){return `<article class="kpi"><span>${name}</span><b>${value}</b><em>${unit}</em></article>`}
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
