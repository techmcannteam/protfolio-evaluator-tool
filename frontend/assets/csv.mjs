// CSV is parsed locally; only reviewed addresses are sent for evaluation.
export const MAX_CSV_BYTES = 100 * 1024;
const aliases = {street:'st',avenue:'ave',road:'rd',lane:'ln',drive:'dr',boulevard:'blvd',terrace:'ter',circle:'cir',court:'ct',place:'pl',pennsylvania:'pa',apartment:'unit',apt:'unit',suite:'unit'};
function addressKey(value) {
  return value.normalize('NFKC').trim().toLowerCase().replace(/#\s*/g,' unit ').replace(/[.,]/g,' ').split(/\s+/).map(word=>aliases[word]||word).join(' ');
}
function validAddress(value) {
  const key = addressKey(value);
  return value.length<=250 && !/[\x00-\x1f\x7f]/.test(value) && /^[0-9][a-z0-9 /-]+$/.test(key) && /\b[a-z]{2} \d{5}(?:-\d{4})?$/.test(key) && key.split(' ').length>=5;
}
export function parseCsv(text) {
  if (typeof text!=='string' || text.length>MAX_CSV_BYTES) throw new Error('Choose a CSV file smaller than 100 KB.');
  text=text.replace(/^\uFEFF/,'');
  const rows=[];let row=[],field='',mode='start';
  const cell=()=>{row.push(field);field='';mode='start';};
  const record=()=>{cell();if(row.some(value=>value.trim()))rows.push(row);row=[];if(rows.length>1001)throw new Error('This CSV has too many rows. Import up to 10 properties at a time.');};
  for(let i=0;i<text.length;i++) {
    const c=text[i];
    if(mode==='quoted') {
      if(c==='"') {if(text[i+1]==='"'){field+='"';i++;}else mode='closed';}
      else field+=c;
      continue;
    }
    if(c===','){cell();continue;}
    if(c==='\r'||c==='\n'){record();if(c==='\r'&&text[i+1]==='\n')i++;continue;}
    if(mode==='closed') {if(c===' '||c==='\t')continue;throw new Error('Malformed CSV: unexpected text after a closing quote.');}
    if(c==='"'){if(mode!=='start')throw new Error('Malformed CSV: put quotes around the entire address field.');mode='quoted';}
    else {field+=c;mode='plain';}
  }
  if(mode==='quoted')throw new Error('Malformed CSV: a quoted field is missing its closing quote.');
  if(field||row.length||mode==='closed')record();
  return rows;
}
export function mergeCsv(text, existing=[]) {
  const rows=parseCsv(text);
  if(rows.length<2)throw new Error('The CSV needs a header row and at least one property. Download the sample template.');
  const headers=rows[0].map(h=>h.trim().toLowerCase().replace(/[ _-]/g,''));
  if(new Set(headers).size!==headers.length)throw new Error('CSV column names must be unique.');
  const find=(...names)=>headers.findIndex(h=>names.includes(h));
  const full=find('fulladdress','formattedaddress');const street=find('address','street','streetaddress','address1');
  const city=find('city'),state=find('state'),zip=find('zip','zipcode','postalcode'),unit=find('unit','apartment','apt','suite','address2');
  const split=city>=0&&state>=0&&zip>=0&&street>=0;
  if(full<0&&street<0)throw new Error('Include an address column, or street, city, state and zip columns.');
  if(full<0&&!split&&[city,state,zip].some(i=>i>=0))throw new Error('Separate address columns need street/address, city, state and zip.');
  const imported=[];
  for(let i=1;i<rows.length;i++) {
    const row=rows[i];
    if(row.length!==headers.length)throw new Error(`CSV row ${i+1} has the wrong number of columns. Put full addresses containing commas inside double quotes.`);
    let address;
    if(full>=0)address=row[full].trim();
    else if(split){
      const part=row[unit]?.trim()||'';
      const unitText=part?(/^(?:unit|apt\.?|apartment|suite|#)\s*/i.test(part)?part:`Unit ${part}`):'';
      address=`${row[street].trim()}${unitText?' '+unitText:''}, ${row[city].trim()}, ${row[state].trim()} ${row[zip].trim()}`;
    }else address=row[street].trim();
    if(!validAddress(address))throw new Error(`CSV row ${i+1}: enter a full street address, city, two-letter state and ZIP. Include the unit number if applicable.`);
    imported.push(address);
  }
  const addresses=existing.map(a=>a.trim()).filter(Boolean), seen=new Set(addresses.map(addressKey));
  let added=0,duplicates=0;
  for(const address of imported){const key=addressKey(address);if(seen.has(key)){duplicates++;continue;}seen.add(key);addresses.push(address);added++;}
  if(addresses.length>10)throw new Error(`This would give you ${addresses.length} properties. The limit is 10 total, including addresses already entered. Nothing was imported.`);
  return {addresses,added,duplicates};
}
