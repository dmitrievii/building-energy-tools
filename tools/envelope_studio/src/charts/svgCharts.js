const NS = 'http://www.w3.org/2000/svg';
function el(name, attrs={}) { const e=document.createElementNS(NS,name); Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v))); return e; }
function extent(values, fallback=[0,1]) { const a=values.filter(Number.isFinite); if(!a.length) return fallback; const lo=Math.min(...a), hi=Math.max(...a); return lo===hi?[lo-1,hi+1]:[lo,hi]; }
function pathD(points, sx, sy) { return points.map((p,i)=>`${i?'L':'M'} ${sx(p.x).toFixed(2)} ${sy(p.y).toFixed(2)}`).join(' '); }

export function lineChart(container, series, {xLabel='', yLabel='', xDomain=null, yDomain=null}={}) {
  container.replaceChildren();
  const width=760,height=300,m={l:58,r:18,t:20,b:42};
  const xs=series.flatMap(s=>s.points.map(p=>p.x)), ys=series.flatMap(s=>s.points.map(p=>p.y));
  const [xmin,xmax]=xDomain??extent(xs), [ymin0,ymax0]=yDomain??extent(ys);
  const pad=(ymax0-ymin0)*0.08 || 1, ymin=ymin0-pad, ymax=ymax0+pad;
  const sx=x=>m.l+(x-xmin)/(xmax-xmin)*(width-m.l-m.r);
  const sy=y=>height-m.b-(y-ymin)/(ymax-ymin)*(height-m.t-m.b);
  const svg=el('svg',{viewBox:`0 0 ${width} ${height}`,role:'img'}); svg.classList.add('chart-svg');
  svg.append(el('line',{x1:m.l,y1:height-m.b,x2:width-m.r,y2:height-m.b,class:'axis'}),el('line',{x1:m.l,y1:m.t,x2:m.l,y2:height-m.b,class:'axis'}));
  for(let i=0;i<=4;i++){const y=ymin+(ymax-ymin)*i/4, py=sy(y); svg.append(el('line',{x1:m.l,y1:py,x2:width-m.r,y2:py,class:'grid'})); const t=el('text',{x:m.l-8,y:py+4,'text-anchor':'end',class:'tick'});t.textContent=Number(y).toFixed(Math.abs(y)<10?1:0);svg.append(t);}
  series.forEach((s,idx)=>{const p=el('path',{d:pathD(s.points,sx,sy),fill:'none',class:`series s${idx}`});svg.append(p);});
  const tx=el('text',{x:(m.l+width-m.r)/2,y:height-10,'text-anchor':'middle',class:'axis-label'});tx.textContent=xLabel;svg.append(tx);
  const ty=el('text',{x:14,y:(m.t+height-m.b)/2,transform:`rotate(-90 14 ${(m.t+height-m.b)/2})`,'text-anchor':'middle',class:'axis-label'});ty.textContent=yLabel;svg.append(ty);
  container.append(svg);
  const legend=document.createElement('div');legend.className='legend';series.forEach((s,i)=>{const item=document.createElement('span');item.innerHTML=`<i class="legend-swatch s${i}"></i>${s.name}`;legend.append(item);});container.append(legend);
}
