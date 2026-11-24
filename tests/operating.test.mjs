import test from 'node:test';
import assert from 'node:assert/strict';
import {operatingEstimate} from '../frontend/assets/operating.mjs';
const p={is_rental:true,value:{estimate:400000},rent:{estimate:2500},details:{annual_taxes:4200},expense_unit_count:3};
const a={vacancy:.05,management:.08,maintenance:.05,insurance_rate:.005,fallback_tax_rate:.014};
test('default financial calculations stay unchanged',()=>assert.equal(operatingEstimate(p,a).noi,18400));
test('annual per-unit maintenance and insurance match server',()=>assert.equal(operatingEstimate(p,{...a,maintenance_mode:'per_unit',maintenance_per_unit:600,insurance_mode:'per_unit',insurance_per_unit:400}).noi,18900));
test('insurance as percent of rent matches server',()=>assert.equal(operatingEstimate(p,{...a,maintenance_mode:'per_unit',maintenance_per_unit:600,insurance_mode:'percent_rent',insurance_rent_rate:.06}).noi,18300));
test('missing unit count withholds cap instead of guessing',()=>assert.equal(operatingEstimate({...p,expense_unit_count:null},{...a,insurance_mode:'per_unit',insurance_per_unit:400}),null));
