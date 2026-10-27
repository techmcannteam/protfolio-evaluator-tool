import {installAutocomplete} from './autocomplete.mjs';
import {mergeCsv, MAX_CSV_BYTES} from './csv.mjs';
const main = document.querySelector('#main');
const dialog = document.querySelector('#cma-dialog');
const DEFAULT_AGENT = {slug:'mike-mccann',full_name:'Mike McCann',first_name:'Mike',title:'The Mike McCann Team · Keller Williams',photo_url:'',phone:'',email:''};
const state = {agent:DEFAULT_AGENT, addresses:[''], result:null, screen:'landing', assumptions:null, defaults:null, submitted:null, ready:false, csvBusy:false, csvMessage:'', csvError:false};
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value);
const compact = value => value == null ? 'Range unavailable' : value >= 1000000 ? `$${(value/1000000).toFixed(2)}M` : `$${Math.round(value/1000)}K`;
const percent = value => value == null ? 'Unavailable' : `${(value*100).toFixed(1)}%`;
const first = () => escape(state.agent.first_name);
const full = () => escape(state.agent.full_name);
const internal = screen => `/evaluator?agent=${encodeURIComponent(state.agent.slug)}${screen==='landing'?'':`#${screen}`}`;
const button = (text, action, outline=false, extra='') => `<button class="button ${outline?'outline':''}" type="button" data-action="${action}" ${extra}>${text}</button>`;
function photo(size='') {
  const initials = state.agent.full_name.split(/\s+/).filter(Boolean).map(s=>s[0]).filter(Boolean).slice(0,2).join('').toUpperCase();
  return `<div class="avatar ${size}" data-avatar><span role="img" aria-label="Initials of ${full()}">${escape(initials)}</span>${state.agent.photo_url?`<img src="${escape(state.agent.photo_url)}" alt="Photo of ${full()}" referrerpolicy="no-referrer">`:''}</div>`;
}
function installPhotos(root=document) {
  root.querySelectorAll('[data-avatar] img').forEach(img=>{
    const fallback=img.previousElementSibling;
    const loaded=()=>{fallback.hidden=true;};
    const failed=()=>{img.remove();fallback.hidden=false;};
    img.addEventListener('load',loaded,{once:true});
    img.addEventListener('error',failed,{once:true});
    if(img.complete) img.naturalWidth ? loaded() : failed();
  });
}
function agentStrip(error=false) {return `<section class="agent-strip">${photo(error?'error':'')}<div class="agent-copy"><span class="eyebrow red">Sent to you by</span><span class="agent-name">${full()}</span><span class="agent-title">${escape(state.agent.title)}</span></div></section>`;}
const logo = '<img class="logo" src="/assets/m-white.png" alt="McCann Real Estate">';
function hero(title,kicker,subtitle='',results=false) {return `<section class="hero ${results?'compact':''}"><header>${logo}${results?`<div class="agent-pill"><div class="agent-copy"><span class="eyebrow">Your agent</span><span class="agent-name">${full()}</span></div>${photo('small')}</div>`:'<span class="eyebrow">Philly &amp; Main Line</span>'}</header><div class="hero-copy"><span class="eyebrow">${kicker}</span><h1>${title}</h1>${subtitle?`<p>${subtitle}</p>`:''}</div></section>`;}
function footer(){return `<footer class="footer">${logo}<span class="serif">The Mike McCann Team</span><span class="eyebrow">Keller Williams Empower · Philadelphia &amp; Main Line</span><p>Each office is independently owned and operated. Equal Housing Opportunity.</p></footer>`;}
function contact(light=false){return `<div class="contact">${state.agent.phone?`<a class="button outline ${light?'white':''}" href="tel:${escape(state.agent.phone.replace(/[^+\d]/g,''))}">Call ${first()}</a>`:`<button class="button outline ${light?'white':''}" disabled>Call ${first()}</button>`}${state.agent.email?`<a class="button outline ${light?'white':''}" href="mailto:${escape(state.agent.email)}">Email ${first()}</a>`:`<button class="button outline ${light?'white':''}" disabled>Email ${first()}</button>`}${!state.agent.phone&&!state.agent.email?'<p class="hint">Agent contact details are not available yet.</p>':''}</div>`;}
function addressFields(){return state.addresses.map((a,i)=>`<div class="field"><label for="address-${i}">Property ${i+1} *</label><div class="input-wrap"><input class="address" id="address-${i}" name="address-${i}" data-address="${i}" type="text" maxlength="250" required autocomplete="street-address" placeholder="Street, city, state and ZIP" value="${escape(a)}">${i?`<button class="remove" type="button" data-remove="${i}" aria-label="Remove property ${i+1}">×</button>`:''}</div></div>`).join('');}
function landing(){return hero("What's your portfolio worth?",'Free portfolio check','See value, rent and return for up to 10 properties. No sign-up.')+agentStrip()+`<section class="content"><div class="intro"><h2>Your Properties</h2><p>Enter each full address, including city, state, ZIP and unit number.</p></div><form id="evaluate-form"><div class="fields">${addressFields()}</div><div class="actions property-actions"><div class="property-buttons"><button class="button outline small" type="button" data-action="add">+ Add another property</button><button type="button" class="button outline small" data-action="csv">Upload CSV</button></div><span class="hint">${state.addresses.length} of 10</span></div><div class="csv-import"><input id="csv-file" type="file" accept=".csv,text/csv" hidden aria-label="Upload property CSV"><p class="hint">Add addresses from a spreadsheet, up to 10 properties total. Your existing addresses stay in place.</p><a href="/assets/property-template.csv" download="mccann-property-template.csv">Download sample CSV</a><details><summary>CSV format help</summary><p class="hint">Use an <b>address</b> column with each full address in double quotes, or separate <b>street, city, state, zip</b> columns and an optional <b>unit</b> column. Save as UTF-8 CSV, up to 100 KB. Review and edit the imported addresses below before evaluating.</p></details><p id="csv-feedback" class="${state.csvError?'error-message':'hint'}" role="status" aria-live="polite">${escape(state.csvMessage)}</p></div><p id="address-error" class="error-message" role="alert"></p><div class="submit-block"><button class="button" type="submit" ${!state.ready?'disabled':''}>See what it's worth</button><span class="hint">Free · No sign-up · Results in seconds</span></div></form></section>`+footer();}
function loading(){return `<section class="fullscreen"><header>${logo}</header><div class="body" role="status"><span class="eyebrow">Your portfolio check</span><h1>Let's Run the Numbers</h1><p>Checking your properties for ${full()}.</p><div class="progress" style="width:100%" aria-hidden="true"></div><div class="steps">Finding your properties<br>Checking value and rent estimates<br>Calculating your portfolio returns</div><p class="hint">This may take a moment. No need to resubmit.</p></div></section>`;}
const specs = p => [p.details.bedrooms!=null?`${p.details.bedrooms} BD`:null,p.details.bathrooms!=null?`${p.details.bathrooms} BA`:null,p.details.squareFootage!=null?`${Number(p.details.squareFootage).toLocaleString()} SQ.FT.`:null].filter(Boolean).join(' | ');
function operating(p){
  if(!p.value || !p.rent) return null;
  const a=state.assumptions, value=p.value.estimate, annual=p.rent.estimate*12;
  const taxes=a.annual_taxes ?? p.details.annual_taxes ?? value*a.fallback_tax_rate;
  const noi=annual*(1-a.vacancy-a.management-a.maintenance)-taxes-value*a.insurance_rate;
  return {noi,cap:noi/value};
}
function totals(){
  const rows=state.result.properties;
  const usable=rows.filter(p=>p.value);
  const complete=rows.every(p=>p.value&&p.rent);
  return {value:usable.reduce((n,p)=>n+p.value.estimate,0),low:usable.length&&usable.every(p=>p.value.low!=null)?usable.reduce((n,p)=>n+p.value.low,0):null,high:usable.length&&usable.every(p=>p.value.high!=null)?usable.reduce((n,p)=>n+p.value.high,0):null,rent:rows.some(p=>p.rent)?rows.reduce((n,p)=>n+(p.rent?.estimate||0),0):null,cap:complete?rows.reduce((n,p)=>n+operating(p).noi,0)/usable.reduce((n,p)=>n+p.value.estimate,0):null,complete};
}
function propertyCard(p,i){
 if(!p.value) return `<article class="card"><h3>${escape(p.address)}</h3><p>${escape(p.error?.message||'Estimate unavailable.')}</p>${button(`Ask ${first()} about this property`,'contact',true)}</article>`;
 const confidence=p.value.confidence, explanations={high:'The available sources broadly agree on this estimate.',medium:'Treat this automated estimate as a ballpark, not an appraisal.',low:`This estimate needs a closer look. ${first()} can sharpen this with a free CMA.`};
 return `<article class="card"><span class="confidence">${escape(confidence)} confidence</span><div class="stack"><h3>${escape(p.address.split(',')[0])}</h3><span class="eyebrow">${escape(p.address.split(',').slice(1).join(','))}</span><span class="eyebrow">${escape(specs(p))}</span></div><div class="stack"><span class="eyebrow red">Estimated value</span><span class="number">${compact(p.value.estimate)}</span><p>${p.value.low!=null&&p.value.high!=null?`Likely between ${compact(p.value.low)} and ${compact(p.value.high)}`:'Provider range unavailable'}</p></div><div class="numbers"><div><span class="eyebrow muted">Rent estimate</span><strong>${money(p.rent?.estimate)}${p.rent?'<small>/mo</small>':''}</strong></div><div><span class="eyebrow muted">Cap rate</span><strong data-cap="${i}">${percent(operating(p)?.cap)}</strong></div></div><p><b>${escape(confidence[0].toUpperCase()+confidence.slice(1))} confidence.</b> ${explanations[confidence]||explanations.medium}</p>${(p.warnings||[]).map(w=>`<p class="notice">${escape(w)}</p>`).join('')}${button('Think this is off? Get a free CMA','cma',true,`data-property="${i}"`)}</article>`;
}
const assumptionFields=[['vacancy','Vacancy',30,.5,'Share of the year a unit sits empty between tenants.'],['management','Property management',25,.5,'Share of gross rent. Set to 0% if you manage it yourself.'],['maintenance','Maintenance & repairs',25,.5,'Share of gross rent for upkeep and repairs.'],['insurance_rate','Insurance',3,.1,'Annual insurance as a share of the property value.'],['fallback_tax_rate','Fallback property taxes',5,.1,'Used only when actual property taxes are unavailable.']];
function assumptions(){return `<section class="assumptions"><details open><summary>Adjust assumptions</summary><p class="hint">Match the costs to how you run things. Defaults are placeholders pending confirmation.</p>${assumptionFields.map(([k,l,max,step,help])=>`<div class="assumption"><div><label for="${k}">${l}</label><output for="${k}" data-output="${k}">${percent(state.assumptions[k])}</output></div><input type="range" id="${k}" data-assumption="${k}" min="0" max="${max}" step="${step}" value="${state.assumptions[k]*100}"><p class="hint">${help}</p></div>`).join('')}<div class="actions" style="margin-bottom:22px"><span class="hint">Cap rates update as you go.</span><button class="button small outline" data-action="reset">Reset</button></div></details></section>`;}
function results(){const t=totals();return hero("Here's What It's Worth",`Your portfolio · ${state.result.properties.length} ${state.result.properties.length===1?'property':'properties'}`,'',true)+`<section class="content summary"><div class="stack"><span class="eyebrow red">Total estimated value</span><span class="number">${t.low!=null&&t.high!=null?`${compact(t.low)} – ${compact(t.high)}`:'Range unavailable'}</span><p>Most likely around <b>${compact(t.value)}</b></p></div><div class="numbers"><div><span class="eyebrow muted">Monthly rent</span><span class="number">${money(t.rent)}</span><span class="hint">${t.complete?'all together':'available estimates only'}</span></div><div><span class="eyebrow muted">Cap rate</span><span class="number" id="total-cap">${percent(t.cap)}</span><span class="hint">a year, before mortgage</span></div></div>${!t.complete?'<p class="notice">Some estimates are unavailable. Totals include only available data; a complete portfolio cap rate cannot be calculated.</p>':''}<p>Cap rate is what your properties earn in a year after typical costs, as a share of what they're worth. It leaves out your mortgage.</p>${button('Think this is off? Get a free CMA','cma')}</section>`+assumptions()+`<section class="content"><h2 class="center" style="margin-bottom:28px">Property by Property</h2><div class="cards">${state.result.properties.map(propertyCard).join('')}</div><p class="notice center" style="margin-top:28px"><b>Estimates are automated and not an appraisal.</b> Ask your agent for a CMA. For a closer look, ask ${first()} for a free CMA.</p><a class="text-link" data-screen="landing" href="${internal('landing')}">Check different properties</a></section>`+footer();}
function errorScreen(){
 const notFound=state.screen==='not-found',tooMany=state.screen==='too-many';
 const title=notFound?"We Couldn't Find That Address":tooMany?'A Bigger Portfolio?':"A Little Trouble with the Numbers";
 return hero(title,'Let’s take another look','',true)+`<section class="content"><div class="error-box"><p>${notFound?'Double-check the street, city, state, ZIP and unit number, then try again.':tooMany?'You can check up to 10 properties at a time. For a larger portfolio, your agent can help.':escape(state.error||'Our estimate service is temporarily unavailable. Please try again in a moment.')}</p></div>${button(notFound?'Edit my addresses':tooMany?'Back to my properties':'Try again',notFound||tooMany?'landing':'retry')}<div class="error-strip">${agentStrip(true)}</div><h2 class="center" style="margin-bottom:20px">Have ${first()} run the numbers</h2>${contact()}<a class="text-link" href="${internal('landing')}" data-screen="landing">Back to my properties</a></section>`+footer();
}
function confirmation(){const s=state.submitted;return `<section class="fullscreen"><header>${logo}</header><div class="body" aria-live="polite"><div class="checkmark" aria-hidden="true">✓</div><span class="eyebrow">${s.sent?'Request sent':'Request saved'}</span><h1>Thank You, ${escape(s.name.split(' ')[0])}</h1><p>${s.sent?`${full()} will reach out with a free CMA for ${escape(s.address)}.`:`Your CMA request for ${escape(s.address)} has been saved for ${full()}.`}</p><p>${s.sent?'Keep an eye on your phone and inbox.':'This is a preview: agent delivery is not connected yet. No notification has been sent.'}</p>${contact(true)}</div><a class="text-link" data-screen="results" href="${internal('results')}">Back to my results</a></section>`;}
function render(){
 main.innerHTML=state.screen==='landing'?landing():state.screen==='loading'?loading():state.screen==='results'&&state.result?results():state.screen==='confirmation'&&state.submitted?confirmation():errorScreen();
 installPhotos(main);
 installAutocomplete(main);
 document.title=`Portfolio Evaluator · ${state.screen==='results'?'Your results':state.screen==='confirmation'?'Request saved':state.screen==='landing'?'Add your properties':'Your portfolio check'}`;
}
function navigate(screen,replace=false){state.screen=screen;history[replace?'replaceState':'pushState']({screen},'',internal(screen));render();window.scrollTo(0,0);main.focus({preventScroll:true});}
function updateRates(){
 document.querySelector('#total-cap').textContent=percent(totals().cap);
 document.querySelectorAll('[data-cap]').forEach(el=>el.textContent=percent(operating(state.result.properties[Number(el.dataset.cap)])?.cap));
 assumptionFields.forEach(([k])=>{document.querySelector(`[data-output="${k}"]`).textContent=percent(state.assumptions[k]);document.getElementById(k).value=state.assumptions[k]*100;});
}
async function api(path,body){
 const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
 let data;try{data=await response.json();}catch{throw new Error('The service could not return an estimate. Please try again later.');}
 if(!response.ok){const error=new Error(response.status===429?'Too many requests. Please wait before trying again.':typeof data.detail==='string'?data.detail:response.status===422?'Please check your full address and form details.':'The service is temporarily unavailable.');error.status=response.status;throw error;}
 return data;
}
async function evaluate(){
 if(state.screen==='loading'||state.csvBusy)return;
 const addresses=state.addresses.map(a=>a.trim()).filter(Boolean);
 if(!addresses.length){if(state.screen!=='landing')navigate('landing');document.querySelector('#address-error').textContent='Add a full property address to continue.';return;}
 if(addresses.length>10){navigate('too-many');return;}
 navigate('loading',true);
 try{
  const result=await api(`/api/evaluate?agent=${encodeURIComponent(state.agent.slug)}`,{addresses,agent:state.agent.slug});
  state.result=result;
  if(!result.properties.some(p=>p.value)){state.error=result.properties[0]?.error?.message;navigate(result.properties.every(p=>p.error?.code==='address_not_found')?'not-found':'unavailable',true);return;}
  state.defaults={...result.properties.find(p=>p.value).assumptions};state.assumptions={...state.defaults};navigate('results',true);
 }catch(error){state.error=error.message;navigate(error.status===422?'not-found':'unavailable',true);}
}
function openCMA(index){
 const eligible=state.result?.properties.map((p,i)=>({p,i})).filter(({p})=>p.estimate_id)||[];
 if(!eligible.length)return;
 dialog.innerHTML=`<button type="button" class="close" data-close aria-label="Close CMA request">×</button><form id="cma-form"><div class="intro"><span class="eyebrow red">Free CMA from ${full()}</span><h2 id="cma-title">Think This Is Off?</h2><p>Ask ${first()} to look at nearby sales and prepare a free comparative market analysis. No cost, no obligation.</p></div><div class="field"><label for="c-property">Which property?</label><select id="c-property" name="property">${eligible.map(({p,i})=>`<option value="${i}" ${i===index?'selected':''}>${escape(p.address)}</option>`).join('')}</select></div><div class="field"><label for="c-name">Full Name *</label><input id="c-name" name="owner_name" required minlength="2" maxlength="150" autocomplete="name"></div><div class="field"><label for="c-email">Email *</label><input id="c-email" name="email" required type="email" autocomplete="email"></div><div class="field"><label for="c-phone">Phone *</label><input id="c-phone" name="phone" required type="tel" minlength="7" maxlength="30" autocomplete="tel" placeholder="(215) 555-0100"></div><div class="field"><label for="c-value">What do you think it's worth? <span class="hint">(optional)</span></label><input id="c-value" name="expected_value" type="number" min="1" max="1000000000" step="any" inputmode="decimal" placeholder="$525,000"></div><div class="field"><label for="c-note">Anything ${first()} should know? <span class="hint">(optional)</span></label><textarea id="c-note" name="note" maxlength="2000" placeholder="Recent improvements, current rent…"></textarea></div><p class="consent">By sending, you agree ${full()} may call, text or email you about this request.</p><p class="notice">Preview: requests are saved, but agent delivery is not connected yet.</p><p id="cma-error" role="alert" class="error-message"></p><button type="submit" class="button">Send to ${first()}</button></form>`;
 dialog.showModal();document.body.classList.add('dialog-open');dialog.querySelector('#c-name').focus();
}
dialog.addEventListener('close',()=>document.body.classList.remove('dialog-open'));
dialog.addEventListener('click',event=>{if(event.target.closest('[data-close]'))dialog.close();});
dialog.addEventListener('submit',async event=>{
 event.preventDefault();const form=event.target, data=new FormData(form), submit=form.querySelector('[type=submit]');
 if(submit.disabled)return;submit.disabled=true;submit.textContent='Saving your request…';
 const property=state.result.properties[Number(data.get('property'))];
 try{
  const payload={estimate_id:property.estimate_id,agent_slug:state.agent.slug,owner_name:data.get('owner_name'),email:data.get('email'),phone:data.get('phone'),note:data.get('note')||'',expected_value:data.get('expected_value')?Number(data.get('expected_value')):null};
  const result=await api('/api/cma-requests',payload);
  state.submitted={name:payload.owner_name,address:property.address,sent:result.fub.sent};dialog.close();navigate('confirmation');
 }catch(error){dialog.querySelector('#cma-error').textContent=error.message;submit.disabled=false;submit.textContent=`Send to ${state.agent.first_name}`;}
});
main.addEventListener('input',event=>{
 if(event.target.matches('[data-address]'))state.addresses[Number(event.target.dataset.address)]=event.target.value;
 if(event.target.matches('[data-assumption]')){state.assumptions[event.target.dataset.assumption]=Number(event.target.value)/100;updateRates();}
});
main.addEventListener('change', async event=>{
 if(event.target.id!=='csv-file')return;
 const input=event.target, file=input.files[0];
 if(!file||state.csvBusy)return;
 state.csvBusy=true;
 const upload=main.querySelector('[data-action="csv"]'), submit=main.querySelector('#evaluate-form [type="submit"]');
 upload.disabled=true;submit.disabled=true;upload.textContent='Reading CSV…';
 try{
  if(!/\.csv$/i.test(file.name))throw new Error('Choose a .csv file. Export Excel workbooks as CSV first.');
  if(file.size>MAX_CSV_BYTES)throw new Error('Choose a CSV file smaller than 100 KB.');
  const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
  if(state.screen!=='landing')return;
  const result=mergeCsv(text,state.addresses);
  state.addresses=result.addresses;
  state.csvError=false;
  state.csvMessage=`${result.added} ${result.added===1?'property':'properties'} imported.${result.duplicates?` ${result.duplicates} duplicate ${result.duplicates===1?'row was':'rows were'} skipped.`:''} Review the addresses below, then select “See what it's worth”.`;
 }catch(error){
  state.csvError=true;
  state.csvMessage=error instanceof TypeError?'Save the file as UTF-8 CSV and try again.':error.message;
 }finally{
  state.csvBusy=false;input.value='';
  if(state.screen==='landing'){render();main.querySelector('[data-action="csv"]').focus();}
 }
});
main.addEventListener('submit',event=>{if(event.target.id==='evaluate-form'){event.preventDefault();evaluate();}});
main.addEventListener('click',event=>{
 const target=event.target.closest('[data-action],[data-screen],[data-remove]');if(!target)return;
 if(target.dataset.screen){event.preventDefault();navigate(target.dataset.screen);return;}
 if(target.dataset.remove){state.addresses.splice(Number(target.dataset.remove),1);render();return;}
 const action=target.dataset.action;
 if(action==='csv'){document.querySelector('#csv-file').click();}
 if(action==='add'){if(state.addresses.length>=10){navigate('too-many');return;}state.addresses.push('');render();document.getElementById(`address-${state.addresses.length-1}`).focus();}
 if(action==='landing')navigate('landing');
 if(action==='retry'){if(!state.ready){boot();}else{evaluate();}}
 if(action==='cma')openCMA(target.hasAttribute('data-property')?Number(target.dataset.property):undefined);
 if(action==='reset'){state.assumptions={...state.defaults};updateRates();}
 if(action==='contact'){navigate('not-found');}
});
window.addEventListener('popstate',()=>{const screen=location.hash.slice(1)||'landing';state.screen=['results','confirmation'].includes(screen)&&!state.result?'landing':screen==='loading'?'landing':screen;render();});
async function boot(){
 const slug=new URLSearchParams(location.search).get('agent');
 const valid=typeof slug==='string'&&/^[a-z0-9-]{1,60}$/.test(slug);
 try{state.agent=await api(`/api/agent${valid?`?slug=${encodeURIComponent(slug)}`:''}`);state.ready=true;state.screen='landing';}
 catch{state.error='We could not load the agent roster. Please refresh and try again.';state.screen='unavailable';}
 history.replaceState({screen:state.screen},'',internal(state.screen));render();
}
boot();
