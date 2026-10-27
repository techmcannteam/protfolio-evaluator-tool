import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseCsv,mergeCsv} from '../frontend/assets/csv.mjs';
const address='2456 Sepviva St, Philadelphia, PA 19125';
test('quoted full addresses, BOM, CRLF and blank rows',()=>{
 assert.deepEqual(mergeCsv('\uFEFFaddress\r\n"'+address+'"\r\n\r\n').addresses,[address]);
 assert.deepEqual(parseCsv('a,b\n"a""b","c\nd"'),[['a','b'],['a"b','c\nd']]);
});
test('split columns keep distinct units and skip normalized duplicates',()=>{
 const result=mergeCsv('street,city,state,zip,unit\n219 S 18th St,Philadelphia,PA,19103,902\n219 S 18th St,Philadelphia,PA,19103,903\n219 S 18th Street,Philadelphia,PA,19103,902');
 assert.equal(result.added,2);assert.equal(result.duplicates,1);assert.match(result.addresses[0],/Unit 902/);
});
test('append to existing and deduplicate without mutating input',()=>{
 const existing=[address,''];const result=mergeCsv('address\n"'+address+'"',existing);
 assert.equal(result.added,0);assert.equal(result.duplicates,1);assert.deepEqual(existing,[address,'']);
});
test('reject malformed, missing, unsafe, oversized and incomplete files',()=>{
 for(const text of ['address','address\n"oops','address\n"oops"x','address\n'+address,'address\n<script>','street,city\n123 Main St,Philadelphia','address,address\na,b','address\n'+'a'.repeat(102401)])assert.throws(()=>mergeCsv(text));
});
test('reject over ten atomically and accept exactly ten',()=>{
 const text='address\n'+Array.from({length:10},(_,i)=>`"${100+i} Main St, Philadelphia, PA 19103"`).join('\n');
 assert.equal(mergeCsv(text).addresses.length,10);
 const existing=[address];assert.throws(()=>mergeCsv(text,existing),/limit is 10/);assert.deepEqual(existing,[address]);
});
test('optional property metadata defaults and validation',()=>{
 const r=mergeCsv('address,property_type,is_rental\n"'+address+'",Rowhome / townhouse,yes');
 assert.equal(r.properties[0].property_type,'Townhouse');assert.equal(r.properties[0].is_rental,true);
 const missing=mergeCsv('address\n"'+address+'"').properties[0];assert.equal(missing.property_type,'');assert.equal(missing.is_rental,false);
 assert.throws(()=>mergeCsv('address,is_rental\n"'+address+'",maybe'),/yes or no/);
 assert.throws(()=>mergeCsv('address,property_type\n"'+address+'",office'),/property_type/);
});
