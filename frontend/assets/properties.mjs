export const propertyTypes = [['Single Family','House'],['Townhouse','Rowhome / townhouse'],['Condo','Condo'],['Multi-Family','2–4 unit']];
export function propertyType(value) {
 const text=String(value||'').trim().toLowerCase();
 const aliases={'rowhome':'Townhouse','townhouse':'Townhouse','2-4 unit':'Multi-Family','2–4 unit':'Multi-Family'};
 return propertyTypes.find(([id,label])=>[id.toLowerCase(),label.toLowerCase()].includes(text))?.[0] || aliases[text] || '';
}
export function propertyRow(value='') {return typeof value==='string'?{address:value,property_type:'',is_rental:false}:{...value};}
