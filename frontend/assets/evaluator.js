import {operatingEstimate} from './operating.mjs';
import {propertyTypes, propertyType, propertyRow, evaluationInputs} from './properties.mjs';
import {installAutocomplete} from './autocomplete.mjs';
import {mergeCsv, MAX_CSV_BYTES} from './csv.mjs';
const main = document.querySelector('#main');
const dialog = document.querySelector('#cma-dialog');
const DEFAULT_AGENT = {slug:'mike-mccann',full_name:'Mike McCann',first_name:'Mike',title:'The Mike McCann Team · Keller Williams',photo_url:'',phone:'',email:''};
const mode = location.pathname==='/evaluator/home'?'home':'portfolio';
const entryPath = mode==='home'?'/evaluator/home':'/evaluator/portfolio';
const state = {linkSlug:null, contact:null, agent:DEFAULT_AGENT, addresses:[propertyRow()], result:null, screen:'landing', assumptions:null, defaults:null, submitted:null, ready:false, csvBusy:false, csvMessage:'', csvError:false};
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value);
const compact = value => value == null ? 'Range unavailable' : value >= 1000000 ? `$${(value/1000000).toFixed(2)}M` : `$${Math.round(value/1000)}K`;
const percent = value => value == null ? 'Unavailable' : `${(value*100).toFixed(1)}%`;
const first = () => escape(state.agent.first_name);
const full = () => escape(state.agent.full_name);
const agentQuery = () => state.linkSlug?`?agent=${encodeURIComponent(state.linkSlug)}`:'';
const internal = screen => `${entryPath}${agentQuery()}${screen==='landing'?'':`#${screen}`}`;
const button = (text, action, outline=false, extra='') => `<button class="button ${outline?'outline':''}" type="button" data-action="${action}" ${extra}>${text}</button>`;
function photo(size='') {
  const initials = state.agent.full_name.split(/\s+/).filter(Boolean).map(s=>s[0]).filter(Boolean).slice(0,2).join('').toUpperCase();
  return `<div class="avatar ${size}" data-avatar><span role="img" aria-label="Initials of ${full()}">${escape(initials)}</span>${state.agent.photo_url?`<img src="${escape(state.agent.photo_url)}" alt="${full()}, The Mike McCann Team" referrerpolicy="no-referrer">`:''}</div>`;
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
function agentStrip(error=false) {return `<section class="agent-strip">${photo(error?'error':'')}<div class="agent-copy"><span class="eyebrow red">${state.linkSlug?'Sent to you by':'Your local team'}</span><span class="agent-name">${full()}</span><span class="agent-title">${escape(state.agent.title)}</span></div></section>`;}
const logo = '<img class="logo" src="/assets/m-white.png" alt="McCann Real Estate">';
function hero(title,kicker,subtitle='',results=false) {return `<section class="hero ${results?'compact':''}"><header>${logo}${results?`<div class="agent-pill"><div class="agent-copy"><span class="eyebrow">Your agent</span><span class="agent-name">${full()}</span></div>${photo('small')}</div>`:'<span class="eyebrow">Philly &amp; Main Line</span>'}</header><div class="hero-copy"><span class="eyebrow">${kicker}</span><h1>${title}</h1>${subtitle?`<p>${subtitle}</p>`:''}</div></section>`;}
function footer(){return `<footer class="footer">${logo}<span class="serif">The Mike McCann Team</span><span class="eyebrow">Keller Williams Empower · Philadelphia &amp; Main Line</span><p>Each office is independently owned and operated. Equal Housing Opportunity.</p></footer>`;}
function contact(light=false){return `<div class="contact">${state.agent.phone?`<a class="button outline ${light?'white':''}" href="tel:${escape(state.agent.phone.replace(/[^+\d]/g,''))}">Call ${first()}</a>`:`<button class="button outline ${light?'white':''}" disabled>Call ${first()}</button>`}${state.agent.email?`<a class="button outline ${light?'white':''}" href="mailto:${escape(state.agent.email)}">Email ${first()}</a>`:`<button class="button outline ${light?'white':''}" disabled>Email ${first()}</button>`}${!state.agent.phone&&!state.agent.email?'<p class="hint">Agent contact details are not available yet.</p>':''}</div>`;}
function conditionField(a,i){return `<div class="field condition-question"><label for="updated-${i}">Kitchen or baths updated in the last 5 years?</label><select id="updated-${i}" data-updated="${i}"><option value="" ${a.recently_updated==null?'selected':''}>Not sure</option><option value="yes" ${a.recently_updated===true?'selected':''}>Yes</option><option value="no" ${a.recently_updated===false?'selected':''}>No</option></select></div>`;}
function contactStep(){const c=state.contact||{};return hero('Your Contact Details','Step 2 of 2','Your results are next.',true)+agentStrip()+`<section class="content"><form id="contact-form"><div class="fields"><div class="field"><label for="owner-name">Name *</label><input id="owner-name" name="name" autocomplete="name" required minlength="2" maxlength="150" value="${escape(c.name||'')}"></div><div class="field"><label for="owner-email">Email *</label><input id="owner-email" name="email" type="email" autocomplete="email" required maxlength="254" value="${escape(c.email||'')}"></div><div class="field"><label for="owner-phone">Phone (optional)</label><input id="owner-phone" name="phone" type="tel" autocomplete="tel" minlength="7" maxlength="30" value="${escape(c.phone||'')}"></div><p class="hint">Your contact details are saved with this evaluation so the team can help with your results. No account required.</p><p id="contact-error" class="error-message" role="alert"></p><button class="button" type="submit">See what it's worth</button><a class="text-link" data-screen="landing" href="${internal('landing')}">Back to addresses</a></div></form></section>`+footer();}
function valueDisplay(p){const d=p.display_value||{most_likely:p.value.estimate,low:p.value.low,high:p.value.high,explanation:''};return `<div class="value-display"><span class="eyebrow red">Most likely value</span><strong class="number most-likely">${money(d.most_likely)}</strong>${d.low!=null&&d.high!=null?`<p class="value-range">${money(d.low)} – ${money(d.high)}</p><div class="condition-scale" aria-hidden="true">${d.position!=null?`<span style="left:${Math.min(100,Math.max(0,d.position*100))}%"></span>`:''}</div><div class="condition-labels"><span>Needs work</span><span>Renovated / updated</span></div>`:'<p>Provider range unavailable</p>'}<p class="condition-explanation">${escape(d.explanation)}</p></div>`;}
function subjectFields(a,i){return `<div class="property-options subject-fields">${[['bedrooms','Bedrooms (if known)',0,1,30],['bathrooms','Bathrooms (if known)',0.5,'any',30],['square_footage','Owner-provided square feet (required for condos)',1,'any',100000]].map(([k,label,min,step,max])=>`<div class="field"><label for="${k}-${i}">${label}</label><input id="${k}-${i}" data-owner="${k}" data-row="${i}" type="number" min="${min}" max="${max}" step="${step}" value="${escape(a[k]??'')}"></div>`).join('')}</div><p class="hint">For houses, enter whole-home facts; for condos, enter your unit's square footage. Use the layouts below for multi-unit buildings.</p>`;}
function ownerFields(a,i){return `<details class="owner-fields"><summary>Unit counts, layouts and actual rent (optional)</summary><p class="hint">Enter owner-provided facts. Leave unknown layouts blank for agent review.</p><div class="property-options">${[['unit_count','Total units'],['residential_unit_count','Residential units'],['actual_monthly_rent','Actual building rent per month']].map(([k,label])=>`<div class="field"><label for="${k}-${i}">${label}</label><input id="${k}-${i}" data-owner="${k}" data-row="${i}" type="number" min="${k==='unit_count'?1:0}" step="${k==='actual_monthly_rent'?'any':1}" value="${escape(a[k]??'')}"></div>`).join('')}</div><div class="field"><label for="owner-source-${i}">Source of owner information</label><input id="owner-source-${i}" data-owner="owner_source" data-row="${i}" maxlength="200" value="${escape(a.owner_source||'Owner-provided')}"></div><div class="field"><label for="unit-mix-${i}">Residential unit layouts</label><textarea id="unit-mix-${i}" data-owner="unit_mix_text" data-row="${i}" rows="3" maxlength="4000" placeholder="2, 1, 1, 650">${escape(a.unit_mix_text||'')}</textarea><p class="hint">One line per layout: number of units, bedrooms, bathrooms, optional square feet. Example: 2, 1, 1, 650 means two 1-bedroom, 1-bath units of 650 square feet each. Use 0 bedrooms for a studio.</p></div></details>`;}
function buildingFacts(p){const b=p.building;return `${b?`<div class="notice"><p><b>${b.unit_count??'Unknown'} total units${b.residential_unit_count!=null?`, ${b.residential_unit_count} residential`:''}</b></p><p>${escape(b.unit_count_provenance?.source==='owner'?'Owner-provided count':'Provider count')}: ${escape(b.unit_count_provenance?.label||'Unknown')}</p>${b.unit_mix_provenance?`<p>Layouts: ${escape(b.unit_mix_provenance.label)}</p>`:'<p>Unit layouts: needs agent review</p>'}${b.mixed_use?`<p>Residential modeled rent: ${money(p.residential_rent?.estimate)}/mo</p><p>Commercial rent: needs agent review</p>`:''}</div>`:''}${p.actual_monthly_rent?`<p>Actual owner rent roll: ${money(p.actual_monthly_rent.amount)}/mo. Source: ${escape(p.actual_monthly_rent.provenance.label)}. Shown separately from modeled rent.</p>`:''}`;}
function addressFields(){return state.addresses.map((a,i)=>`<div class="field"><label for="address-${i}">Property ${i+1} *</label><div class="input-wrap"><input class="address" id="address-${i}" name="address-${i}" data-address="${i}" type="text" maxlength="250" required autocomplete="street-address" placeholder="Street, city, state and ZIP" value="${escape(a.address)}">${i?`<button class="remove" type="button" data-remove="${i}" aria-label="Remove property ${i+1}">×</button>`:''}</div><div class="property-options"><div><label for="type-${i}">Property type *</label><select id="type-${i}" data-property-type="${i}" required><option value="">Select property type</option>${propertyTypes.map(([value,label])=>`<option value="${value}" ${a.property_type===value?'selected':''}>${label}</option>`).join('')}</select></div><label class="rental-option" for="rental-${i}"><input id="rental-${i}" type="checkbox" data-rental="${i}" ${a.is_rental?'checked':''}>This is a rental.</label></div><p class="hint" data-record-status="${i}" role="status">${escape(a.recordMessage||'')}</p>${conditionField(a,i)}${mode==='home'?`<details class="home-details"><summary>Property details (square footage required for condos)</summary>${subjectFields(a,i)}${ownerFields(a,i)}</details>`:`${subjectFields(a,i)}${ownerFields(a,i)}`}</div>`).join('');}
function landing(){return hero(mode==='home'?"What's your home worth?":"What's your portfolio worth?",mode==='home'?'Free home evaluation':'Free portfolio check',mode==='home'?'A clear starting point for your home’s value.':'See value, rent and return for up to 10 properties.')+agentStrip()+`<section class="content"><div class="intro"><span class="eyebrow red">Step 1 of 2</span><h2>${mode==='home'?'Your Home':'Your Properties'}</h2><p>Enter each full address, including city, state, ZIP and unit number.</p></div><form id="evaluate-form"><div class="fields">${addressFields()}</div>${mode==='portfolio'?`<div class="actions property-actions"><div class="property-buttons"><button class="button outline small" type="button" data-action="add">+ Add another property</button><button type="button" class="button outline small" data-action="csv">Upload CSV</button></div><span class="hint">${state.addresses.length} of 10</span></div><input id="csv-file" type="file" accept=".csv,text/csv" hidden aria-label="Upload property CSV"><details class="csv-help"><summary><span>CSV template &amp; instructions</span><span class="csv-help-toggle" aria-hidden="true"></span></summary><div class="csv-help-content"><p>Add addresses from a spreadsheet, up to 10 properties total. Your existing addresses stay in place.</p><a class="button outline small" href="/assets/property-template.csv" download="mccann-property-template.csv">Download sample CSV</a><p>Use an <b>address</b> column with each full address in double quotes, or separate <b>street, city, state, zip</b> columns and an optional <b>unit</b> column. Optional <b>property_type</b>: House, Rowhome / townhouse, Condo, 2–4 unit, 5+ unit building, Mixed-use building, or Manufactured. Optional <b>is_rental</b>: yes/no. Optional owner fields: <b>bedrooms, bathrooms, square_footage, unit_count, residential_unit_count, owner_source, actual_monthly_rent</b>. Condos require owner-provided <b>square_footage</b> before evaluation. Missing type is looked up from the property record; missing rental status defaults to no.</p><p class="hint">Save as UTF-8 CSV, up to 100 KB. Review and edit the imported addresses before evaluating.</p></div></details><p id="csv-feedback" class="${state.csvError?'error-message':'hint'}" role="status" aria-live="polite">${escape(state.csvMessage)}</p>`:''}<p id="address-error" class="error-message" role="alert"></p><div class="submit-block"><button class="button" type="submit" ${!state.ready?'disabled':''}>Continue</button><span class="hint">Next: your contact details</span></div></form></section>`+footer();}
function loading(){return `<section class="fullscreen"><header>${logo}</header><div class="body" role="status"><span class="eyebrow">Your portfolio check</span><h1>Let's Run the Numbers</h1><p>Checking your properties for ${full()}.</p><div class="progress" style="width:100%" aria-hidden="true"></div><div class="steps">Finding your properties<br>Checking value and rent estimates<br>Calculating your portfolio returns</div><p class="hint">This may take a moment. No need to resubmit.</p></div></section>`;}
const specs = p => [p.details.bedrooms!=null?`${p.details.bedrooms} BD`:null,p.details.bathrooms!=null?`${p.details.bathrooms} BA`:null,p.details.squareFootage!=null?`${Number(p.details.squareFootage).toLocaleString()} SQ.FT.`:null].filter(Boolean).join(' | ');
function operating(p){return operatingEstimate(p,state.assumptions);}
function totals(){
  const rows=state.result.properties;
  const usable=rows.filter(p=>p.value);
  const rentals=rows.filter(p=>p.is_rental);
  const complete=rows.every(p=>p.value&&p.rent);
  const rentalComplete=rentals.length&&rentals.every(p=>operating(p));
  return {value:usable.length?usable.reduce((n,p)=>n+(p.display_value?.most_likely??p.value.estimate),0):null,low:usable.length&&usable.every(p=>p.value.low!=null)?usable.reduce((n,p)=>n+p.value.low,0):null,high:usable.length&&usable.every(p=>p.value.high!=null)?usable.reduce((n,p)=>n+p.value.high,0):null,rent:rows.every(p=>p.rent)?rows.reduce((n,p)=>n+p.rent.estimate,0):null,cap:rentalComplete?rentals.reduce((n,p)=>n+operating(p).noi,0)/rentals.reduce((n,p)=>n+p.value.estimate,0):null,complete,rentals:rentals.length};
}
function propertyCard(p,i){
 if(!p.value) return `<article class="card"><h3>${escape(p.address)}</h3><p>${escape(p.error?.message||'Estimate unavailable.')}</p>${buildingFacts(p)}${(p.warnings||[]).map(w=>`<p class="notice">${escape(w)}</p>`).join('')}${button(`Ask ${first()} about this property`,'contact',true)}</article>`;
 const confidence=p.value.confidence, explanations={high:'The available sources broadly agree on this estimate.',medium:'Treat this automated estimate as a ballpark, not an appraisal.',low:`This estimate needs a closer look. ${first()} can sharpen this with a free CMA.`};
 return `<article class="card"><span class="confidence">${escape(confidence)} confidence</span><div class="stack"><h3>${escape(p.address.split(',')[0])}</h3><span class="eyebrow">${escape(p.address.split(',').slice(1).join(','))}</span><span class="eyebrow">${escape(specs(p))}</span><span class="hint">${escape(propertyTypes.find(([value])=>value===p.property_type)?.[1]||p.property_type||'')} · ${p.is_rental?'Rental':'Not currently a rental'}</span></div>${valueDisplay(p)}${buildingFacts(p)}<div class="numbers"><div><span class="eyebrow muted">${p.is_rental?(p.building?'Modeled building rent':'Rent estimate'):'What it could rent for'}</span><strong>${p.needs_agent_review&&!p.rent?'Needs agent review':money(p.rent?.estimate)}${p.rent?'<small>/mo</small>':''}</strong></div>${p.is_rental?`<div><span class="eyebrow muted">Cap rate</span><strong data-cap="${i}">${percent(operating(p)?.cap)}</strong></div>`:''}</div>${p.rent?`<p>Rent range: ${money(p.rent.low)} – ${money(p.rent.high)} /mo${p.building?' (sum of unit ranges)':''}</p>`:''}<p><b>${escape(confidence[0].toUpperCase()+confidence.slice(1))} confidence.</b> ${explanations[confidence]||explanations.medium}</p>${(p.warnings||[]).map(w=>`<p class="notice">${escape(w)}</p>`).join('')}${button('Think this is off? Get a free CMA','cma',true,`data-property="${i}"`)}</article>`;
}
const baseAssumptionFields=[['vacancy','Vacancy',30,.5,'Share of the year a unit sits empty between tenants.'],['management','Property management',25,.5,'Share of gross rent. Set to 0% if you manage it yourself.'],['maintenance','Maintenance & repairs',25,.5,'Share of gross rent for upkeep and repairs.'],['insurance_rate','Insurance',3,.1,'Annual insurance as a share of the property value.'],['fallback_tax_rate','Fallback property taxes',5,.1,'Used only when actual property taxes are unavailable.']];
function assumptionFields(){
 return baseAssumptionFields.map(row=>{
  if(row[0]==='maintenance'&&state.assumptions.maintenance_mode==='per_unit')return ['maintenance_per_unit','Maintenance & repairs',10000,50,'Annual dollars per verified unit.',1];
  if(row[0]==='insurance_rate'&&state.assumptions.insurance_mode==='per_unit')return ['insurance_per_unit','Insurance',10000,50,'Annual dollars per verified unit.',1];
  if(row[0]==='insurance_rate'&&state.assumptions.insurance_mode==='percent_rent')return ['insurance_rent_rate','Insurance',25,.5,'Annual insurance as a share of gross rent.',100];
  return [...row,100];
 });
}
function assumptions(){return `<section class="assumptions"><details open><summary>Adjust assumptions</summary><p class="hint">Match the costs to how you run things. Defaults are placeholders pending confirmation.</p>${assumptionFields().map(([k,l,max,step,help,scale])=>`<div class="assumption"><div><label for="${k}">${l}</label><output for="${k}" data-output="${k}">${scale===1?money(state.assumptions[k])+' /unit/year':percent(state.assumptions[k])}</output></div><input type="range" id="${k}" data-assumption="${k}" data-scale="${scale}" min="0" max="${Math.max(max,state.assumptions[k]*scale)}" step="${step}" value="${state.assumptions[k]*scale}"><p class="hint">${help}</p></div>`).join('')}<div class="actions" style="margin-bottom:22px"><span class="hint">Cap rates update as you go.</span><button class="button small outline" data-action="reset">Reset</button></div></details></section>`;}
function results(){const t=totals();const portfolio=mode==='portfolio';return hero("Here's What It's Worth",portfolio?`Your portfolio · ${state.result.properties.length} ${state.result.properties.length===1?'property':'properties'}`:'Your home evaluation','',true)+(portfolio?`<section class="content summary"><div class="stack"><span class="eyebrow red">Most likely portfolio value</span><span class="number">${t.value==null?'Needs agent review':money(t.value)}</span><p>${t.low!=null&&t.high!=null?`${money(t.low)} – ${money(t.high)}`:'Range unavailable'}</p><div class="condition-labels"><span>Needs work</span><span>Renovated / updated</span></div></div><div class="numbers"><div><span class="eyebrow muted">Potential monthly rent</span><span class="number">${money(t.rent)}</span><span class="hint">${t.complete?'all together':'complete building income required'}</span></div>${t.rentals?`<div><span class="eyebrow muted">Rental portfolio cap rate</span><span class="number" id="total-cap">${percent(t.cap)}</span><span class="hint">rentals only · before mortgage</span></div>`:''}</div>${!t.complete?'<p class="notice">Some properties need agent review. Value includes available estimates only; building rent and cap rate require complete income.</p>':''}</section>`:'')+(portfolio&&state.result.properties.some(p=>p.is_rental&&p.value&&p.rent)?assumptions():'')+`<section class="content">${portfolio?'<h2 class="center" style="margin-bottom:28px">Property by Property</h2>':''}<div class="cards">${state.result.properties.map(propertyCard).join('')}</div>${state.result.properties.some(p=>p.display_value?.condition_applied&&p.is_rental)?'<p class="hint">Cap rates use the provider estimate and operating assumptions. Your condition answer changes only the displayed value indication.</p>':''}<p id="summary-email-status" class="hint" role="status">Email delivery is disabled in this review version.</p><p class="notice center" style="margin-top:28px">Estimates are automated and not an appraisal. Ask your agent for a CMA.</p><a class="text-link" data-screen="landing" href="${internal('landing')}">Check different properties</a></section>`+footer();}
function errorScreen(){
 const notFound=state.screen==='not-found',tooMany=state.screen==='too-many';
 const title=notFound?"We Couldn't Find That Address":tooMany?'A Bigger Portfolio?':"A Little Trouble with the Numbers";
 return hero(title,'Let’s take another look','',true)+`<section class="content"><div class="error-box"><p>${notFound?'Double-check the street, city, state, ZIP and unit number, then try again.':tooMany?'You can check up to 10 properties at a time. For a larger portfolio, your agent can help.':escape(state.error||'Our estimate service is temporarily unavailable. Please try again in a moment.')}</p></div>${button(notFound?'Edit my addresses':tooMany?'Back to my properties':'Try again',notFound||tooMany?'landing':'retry')}<div class="error-strip">${agentStrip(true)}</div><h2 class="center" style="margin-bottom:20px">Have ${first()} run the numbers</h2>${contact()}<a class="text-link" href="${internal('landing')}" data-screen="landing">Back to my properties</a></section>`+footer();
}
function confirmation(){const s=state.submitted;return `<section class="fullscreen"><header>${logo}</header><div class="body" aria-live="polite">${photo()}<div class="checkmark" aria-hidden="true">✓</div><span class="eyebrow">${s.sent?'Request sent':'Request saved'}</span><h1>Thank You, ${escape(s.name.split(' ')[0])}</h1><p>${s.sent?`${full()} will reach out with a free CMA for ${escape(s.address)}.`:`Your CMA request for ${escape(s.address)} has been saved for ${full()}.`}</p><p>${s.sent?'Keep an eye on your phone and inbox.':'This is a preview: agent delivery is not connected yet. No notification has been sent.'}</p>${contact(true)}</div><a class="text-link" data-screen="results" href="${internal('results')}">Back to my results</a></section>`;}
function render(){
 main.innerHTML=state.screen==='landing'?landing():state.screen==='contact'?contactStep():state.screen==='loading'?loading():state.screen==='results'&&state.result?results():state.screen==='confirmation'&&state.submitted?confirmation():errorScreen();
 installPhotos(main);
 installAutocomplete(main);
 if(state.screen==='landing')state.addresses.forEach((row,i)=>resolveRecord(i));
 document.title=`${mode==='home'?'Home':'Portfolio'} Evaluator · ${state.screen==='results'?'Your results':state.screen==='confirmation'?'Request saved':state.screen==='landing'?'Add your properties':'Your portfolio check'}`;
}
function navigate(screen,replace=false){state.screen=screen;history[replace?'replaceState':'pushState']({screen},'',internal(screen));render();window.scrollTo(0,0);main.focus({preventScroll:true});}
function updateRates(){
 const totalCap=document.querySelector('#total-cap');if(totalCap)totalCap.textContent=percent(totals().cap);
 document.querySelectorAll('[data-cap]').forEach(el=>el.textContent=percent(operating(state.result.properties[Number(el.dataset.cap)])?.cap));
 assumptionFields().forEach(([k,l,max,step,help,scale])=>{document.querySelector(`[data-output="${k}"]`).textContent=scale===1?money(state.assumptions[k])+' /unit/year':percent(state.assumptions[k]);document.getElementById(k).value=state.assumptions[k]*scale;});
}
async function api(path,body){
 const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
 let data;try{data=await response.json();}catch{throw new Error('The service could not return an estimate. Please try again later.');}
 if(!response.ok){const error=new Error(response.status===429?'Too many requests. Please wait before trying again.':typeof data.detail==='string'?data.detail:response.status===422?'Please check your full address and form details.':'The service is temporarily unavailable.');error.status=response.status;throw error;}
 return data;
}
async function evaluate(withContact=false){
 if(state.screen==='loading'||state.csvBusy)return;
 let addresses;try{addresses=state.addresses.filter(p=>p.address.trim()).map(p=>({address:p.address.trim(),property_type:p.property_type||null,is_rental:p.is_rental,recently_updated:p.recently_updated??null,...evaluationInputs(p)}));}catch(error){document.querySelector('#address-error').textContent=error.message;return;}
 if(!addresses.length){if(state.screen!=='landing')navigate('landing');document.querySelector('#address-error').textContent='Add a full property address to continue.';return;}
 if(mode==='home'&&addresses.length!==1){navigate('landing');return;}
 if(addresses.length>10){navigate('too-many');return;}
 if(addresses.some(p=>!p.property_type)){if(state.screen!=='landing')navigate('landing');document.querySelector('#address-error').textContent='Select a property type for each address.';return;}
 if(!withContact){navigate('contact');return;}
 navigate('loading',true);
 try{
  const result=await api(`/api/evaluate${agentQuery()}`,{addresses,agent:state.linkSlug,mode,contact:state.contact});
  state.result=result;
  if(!result.properties.some(p=>p.value||p.needs_agent_review)){state.error=result.properties[0]?.error?.message;navigate(result.properties.every(p=>p.error?.code==='address_not_found')?'not-found':'unavailable',true);return;}
  state.defaults={...result.properties[0].assumptions};state.assumptions={...state.defaults};navigate('results',true);
  if(result.evaluation_id)requestAnimationFrame(()=>requestAnimationFrame(()=>{api(`/api/evaluations/${result.evaluation_id}/results-shown`,{}).then(status=>{const message=document.querySelector('#summary-email-status');if(message)message.textContent=status.owner_email==='sent'?'Your results summary has been emailed.':status.owner_email==='simulated'?'Your results summary was prepared. Email delivery is simulated.':status.owner_email==='disabled'?'Your results are saved. Email delivery is not enabled.':'Your results are saved. Email delivery needs follow-up.';}).catch(()=>{const message=document.querySelector('#summary-email-status');if(message)message.textContent='Your results are ready. Email delivery is unavailable.';});}));
 }catch(error){state.error=error.message;if(error.status===422){navigate('contact',true);document.querySelector('#contact-error').textContent='Please check your contact details and property information.';}else navigate('unavailable',true);}
}
function openCMA(index){
 const eligible=state.result?.properties.map((p,i)=>({p,i})).filter(({p})=>p.estimate_id)||[];
 if(!eligible.length)return;
 dialog.innerHTML=`<button type="button" class="close" data-close aria-label="Close CMA request">×</button><form id="cma-form"><div class="intro">${photo()}<span class="eyebrow red">Free CMA from ${full()}</span><h2 id="cma-title">Think This Is Off?</h2><p>Ask ${first()} to look at nearby sales and prepare a free comparative market analysis. No cost, no obligation.</p></div><div class="field"><label for="c-property">Which property?</label><select id="c-property" name="property">${eligible.map(({p,i})=>`<option value="${i}" ${i===index?'selected':''}>${escape(p.address)}</option>`).join('')}</select></div><div class="field"><label for="c-name">Full Name *</label><input id="c-name" name="owner_name" required minlength="2" maxlength="150" autocomplete="name"></div><div class="field"><label for="c-email">Email *</label><input id="c-email" name="email" required type="email" autocomplete="email"></div><div class="field"><label for="c-phone">Phone *</label><input id="c-phone" name="phone" required type="tel" minlength="7" maxlength="30" autocomplete="tel" placeholder="(215) 555-0100"></div><div class="field"><label for="c-value">What do you think it's worth? <span class="hint">(optional)</span></label><input id="c-value" name="expected_value" type="number" min="1" max="1000000000" step="any" inputmode="decimal" placeholder="$525,000"></div><div class="field"><label for="c-note">Anything ${first()} should know? <span class="hint">(optional)</span></label><textarea id="c-note" name="note" maxlength="2000" placeholder="Recent improvements, current rent…"></textarea></div><p class="consent">By sending, you agree ${full()} may call, text or email you about this request.</p><p class="notice">Your request is saved before delivery. We’ll confirm its status after you submit.</p><p id="cma-error" role="alert" class="error-message"></p><button type="submit" class="button">Send to ${first()}</button></form>`;
 installPhotos(dialog);dialog.showModal();document.body.classList.add('dialog-open');dialog.querySelector('#c-name').focus();
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
 if(event.target.matches('[data-owner]'))state.addresses[Number(event.target.dataset.row)][event.target.dataset.owner]=event.target.value;
 if(event.target.matches('[data-address]')){const row=state.addresses[Number(event.target.dataset.address)];const changed=row.address!==event.target.value;row.address=event.target.value;if(changed){row.recordAddress='';for(const k of ['unit_count','residential_unit_count','actual_monthly_rent','unit_mix_text','bedrooms','bathrooms','square_footage','recently_updated']){delete row[k];const field=main.querySelector(`[data-owner="${k}"][data-row="${event.target.dataset.address}"]`);if(field)field.value='';}const updated=main.querySelector(`[data-updated="${event.target.dataset.address}"]`);if(updated)updated.value='';}if(changed&&!row.typeManual){row.property_type='';const select=main.querySelector(`[data-property-type="${event.target.dataset.address}"]`);if(select)select.value='';}}
 if(event.target.matches('[data-assumption]')){state.assumptions[event.target.dataset.assumption]=Number(event.target.value)/Number(event.target.dataset.scale);updateRates();}
});
main.addEventListener('change', async event=>{
 if(event.target.matches('[data-updated]')){state.addresses[Number(event.target.dataset.updated)].recently_updated=event.target.value===''?null:event.target.value==='yes';return;}
 if(event.target.matches('[data-property-type]')){const row=state.addresses[Number(event.target.dataset.propertyType)];row.property_type=event.target.value;row.typeManual=true;return;}
 if(event.target.matches('[data-rental]')){state.addresses[Number(event.target.dataset.rental)].is_rental=event.target.checked;return;}
 if(event.target.id!=='csv-file'||mode==='home')return;
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
  state.addresses=result.properties;
  state.csvError=false;
  state.csvMessage=`${result.added} ${result.added===1?'property':'properties'} imported.${result.duplicates?` ${result.duplicates} duplicate ${result.duplicates===1?'row was':'rows were'} skipped.`:''} Review the addresses below, then select “Continue”.`;
 }catch(error){
  state.csvError=true;
  state.csvMessage=error instanceof TypeError?'Save the file as UTF-8 CSV and try again.':error.message;
 }finally{
  state.csvBusy=false;input.value='';
  if(state.screen==='landing'){render();main.querySelector('[data-action="csv"]').focus();}
 }
});
main.addEventListener('submit',event=>{
 if(event.target.id==='evaluate-form'){event.preventDefault();evaluate();}
 if(event.target.id==='contact-form'){event.preventDefault();const data=new FormData(event.target);state.contact={name:data.get('name').trim(),email:data.get('email').trim(),phone:data.get('phone').trim()||null};if(state.contact.phone&&!/^\+?[0-9 ()\-.]{7,30}$/.test(state.contact.phone)){document.querySelector('#contact-error').textContent='Enter a valid phone number, or leave it blank.';return;}evaluate(true);}
});
main.addEventListener('click',event=>{
 const target=event.target.closest('[data-action],[data-screen],[data-remove]');if(!target)return;
 if(target.dataset.screen){event.preventDefault();navigate(target.dataset.screen);return;}
 if(target.dataset.remove){state.addresses.splice(Number(target.dataset.remove),1);render();return;}
 const action=target.dataset.action;
 if(action==='csv'&&mode==='portfolio'){document.querySelector('#csv-file').click();}
 if(action==='add'&&mode==='portfolio'){if(state.addresses.length>=10){navigate('too-many');return;}state.addresses.push(propertyRow());render();document.getElementById(`address-${state.addresses.length-1}`).focus();}
 if(action==='landing')navigate('landing');
 if(action==='retry'){if(!state.ready){boot();}else{evaluate();}}
 if(action==='cma')openCMA(target.hasAttribute('data-property')?Number(target.dataset.property):undefined);
 if(action==='reset'){state.assumptions={...state.defaults};updateRates();}
 if(action==='contact'){navigate('not-found');}
});
window.addEventListener('popstate',()=>{const screen=location.hash.slice(1)||'landing';state.screen=['results','confirmation','contact'].includes(screen)&&!state.result?'landing':screen==='loading'?'landing':screen;render();});
async function boot(){
 const slug=new URLSearchParams(location.search).get('agent');
 const valid=typeof slug==='string'&&/^[a-z0-9-]{1,60}$/.test(slug);
 try{state.agent=await api(`/api/agent${valid?`?slug=${encodeURIComponent(slug)}`:''}`);state.linkSlug=valid&&state.agent.slug===slug?slug:null;state.ready=true;state.screen='landing';}
 catch{state.error='We could not load the agent roster. Please refresh and try again.';state.screen='unavailable';}
 history.replaceState({screen:state.screen},'',internal(state.screen));render();
}
boot();

async function resolveRecord(index){
 const row=state.addresses[index];if(!row||!/[A-Za-z]{2} \d{5}(?:-\d{4})?$/.test(row.address.trim())||row.recordAddress===row.address)return;
 const address=row.address;row.recordAddress=address;row.recordMessage='Looking up property type…';
 const update=()=>{if(state.screen!=='landing'||state.addresses[index]!==row)return;const select=main.querySelector(`[data-property-type="${index}"]`),status=main.querySelector(`[data-record-status="${index}"]`);if(select)select.value=row.property_type;if(status)status.textContent=row.recordMessage;};update();
 try{const data=await api('/api/property-record',{address});if(row.address!==address)return;const type=propertyType(data.property_type);if(!row.typeManual&&!row.property_type)row.property_type=type;row.recordMessage=type?'Property record checked. You can change the type.':'Choose a property type; it was not available in the record.';}
 catch{if(row.address!==address)return;row.recordMessage='Choose a property type; the record lookup is unavailable.';}
 update();
}
main.addEventListener('focusout',event=>{if(event.target.matches('[data-address]'))resolveRecord(Number(event.target.dataset.address));});
main.addEventListener('address-resolved',event=>resolveRecord(Number(event.target.dataset.address)));
