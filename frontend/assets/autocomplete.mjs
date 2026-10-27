// Suggestions are transient. The API key stays on the server.
export function installAutocomplete(root) {
 root.querySelectorAll('[data-address]').forEach(input=>{
  const wrap=input.closest('.field');
  const panel=document.createElement('div');panel.className='address-suggestions';panel.hidden=true;
  const list=document.createElement('div');list.id=input.id+'-suggestions';list.setAttribute('role','listbox');list.setAttribute('aria-label','Suggested addresses');
  const credit=document.createElement('div');credit.className='places-credit';credit.textContent='Google Maps';
  panel.append(list,credit);wrap.append(panel);
  const status=document.createElement('p');status.className='hint address-status';status.setAttribute('role','status');wrap.append(status);
  input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls',list.id);input.setAttribute('aria-expanded','false');input.autocomplete='off';
  let timer,controller,version=0,items=[],active=-1,token=crypto.randomUUID();
  const close=()=>{panel.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;};
  const cancel=()=>{clearTimeout(timer);controller?.abort();version++;close();};
  async function request(path,params){controller=new AbortController();const response=await fetch(path+'?'+new URLSearchParams(params),{signal:controller.signal});if(!response.ok)throw Error('Unavailable');return response.json();}
  async function select(index){
   const item=items[index];if(!item)return;cancel();const current=version;status.textContent='Completing address…';
   try{const data=await request('/api/address-details',{place_id:item.id,token});if(current!==version||!input.isConnected)return;
    input.value=data.address;input.dispatchEvent(new Event('input',{bubbles:true}));cancel();status.textContent='Address selected. Add or check the unit number if applicable.';input.focus();
   }catch(error){if(current===version&&error.name!=='AbortError')status.textContent='Could not complete this address. Enter the street, city, state and ZIP manually.';}
   finally{token=crypto.randomUUID();}
  }
  input.addEventListener('input',()=>{
   cancel();status.textContent='';const q=input.value.trim(),current=version;if(q.length<4)return;
   timer=setTimeout(async()=>{
    try{const data=await request('/api/address-suggestions',{q,token});if(current!==version||!input.isConnected||document.activeElement!==input)return;
     items=data.suggestions;list.replaceChildren();
     items.forEach((item,i)=>{const option=document.createElement('div');option.id=list.id+'-'+i;option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.textContent=item.label;option.addEventListener('mousedown',e=>e.preventDefault());option.addEventListener('click',()=>select(i));list.append(option);});
     panel.hidden=!items.length;input.setAttribute('aria-expanded',String(!!items.length));status.textContent=items.length?'Use arrow keys and Enter to select an address.':'No matches. Enter the full address manually.';
    }catch(error){if(current===version&&error.name!=='AbortError')status.textContent='Suggestions unavailable. You can still enter the full address manually.';}
   },350);
  });
  input.addEventListener('keydown',event=>{
   if(event.key==='Escape'){cancel();return;}
   if(panel.hidden)return;
   if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();active=(active+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;[...list.children].forEach((el,i)=>el.setAttribute('aria-selected',String(i===active)));input.setAttribute('aria-activedescendant',list.children[active].id);list.children[active].scrollIntoView({block:'nearest'});}
   if(event.key==='Enter'){event.preventDefault();if(active>=0)select(active);}
  });
  input.addEventListener('blur',()=>{clearTimeout(timer);setTimeout(close,180);});
 });
}
