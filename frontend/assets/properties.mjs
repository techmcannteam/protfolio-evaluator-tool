export const propertyTypes = [['Single Family','House'],['Townhouse','Rowhome / townhouse'],['Condo','Condo'],['Multi-Family','2–4 unit'],['Apartment','5+ unit building'],['Mixed Use','Mixed-use building']];
export function propertyType(value) {
 const text=String(value||'').trim().toLowerCase();
 const aliases={'rowhome':'Townhouse','townhouse':'Townhouse','2-4 unit':'Multi-Family','2–4 unit':'Multi-Family'};
 return propertyTypes.find(([id,label])=>[id.toLowerCase(),label.toLowerCase()].includes(text))?.[0] || aliases[text] || '';
}
export function propertyRow(value='') {return typeof value==='string'?{address:value,property_type:'',is_rental:false}:{...value};}

export function ownerInputs(row) {
 const result={owner_source:String(row.owner_source||'Owner-provided').trim()};
 for(const key of ['unit_count','residential_unit_count','actual_monthly_rent']) {
  if(row[key]==null||String(row[key]).trim()==='')continue;
  const n=Number(row[key]);
  if(!Number.isFinite(n)||n<0||(key!=='actual_monthly_rent'&&(!Number.isInteger(n)||n>500))||(key==='unit_count'&&n===0))throw new Error('Enter valid unit counts and rent. Leave unknown fields blank.');
  result[key]=n;
 }
 if(result.residential_unit_count!=null&&(result.unit_count==null||result.residential_unit_count>result.unit_count))throw new Error('Residential units must not exceed total units.');
 if(row.unit_mix_text?.trim()) {
  result.unit_mix=row.unit_mix_text.trim().split(/\r?\n/).map(line=>{
   const cells=line.split(',').map(s=>s.trim());
   if(cells.length<3||cells.length>4||cells.slice(0,3).some(s=>s===''))throw new Error('Each layout needs units, bedrooms, bathrooms, and optional square feet.');
   const [count,bedrooms,bathrooms]=cells.slice(0,3).map(Number);
   const square_footage=cells[3]?Number(cells[3]):null;
   if(!Number.isInteger(count)||count<1||!Number.isInteger(bedrooms)||bedrooms<0||!Number.isFinite(bathrooms)||bathrooms<=0||(square_footage!=null&&(!Number.isFinite(square_footage)||square_footage<=0)))throw new Error('Enter a valid unit layout; zero bedrooms is a studio.');
   return {count,bedrooms,bathrooms,square_footage};
  });
  if(result.unit_mix.reduce((n,u)=>n+u.count,0)!==(result.residential_unit_count??result.unit_count))throw new Error('Layout counts must equal the residential unit count, or total units for residential buildings.');
  if(row.property_type==='Mixed Use'&&result.residential_unit_count==null)throw new Error('Enter the residential unit count for a mixed-use building.');
 }
 return result;
}
