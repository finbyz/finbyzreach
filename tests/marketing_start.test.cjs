const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
    const html=new Map(),routes=[];
    const frappe={pages:{'megasol-marketing-start':{}},utils:{escape_html:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')},datetime:{str_to_user:value=>value},set_route:(...args)=>routes.push(args)};
    const context={frappe,Intl,Date,__:text=>text};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../finbyzreach/finbyzreach/page/megasol_marketing_start/megasol_marketing_start.js'),'utf8')+'\nglobalThis.Start = MegasolMarketingStart;',context);
    const page=Object.create(context.Start.prototype);
    page.page={main:{find:selector=>({html:value=>html.set(selector,value)})}};
    return {page,html,routes};
}

test('Start escapes campaign names and distinguishes unavailable delivery from zero',()=>{
    const {page,html}=setup();
    page.data={can_read_campaigns:true,can_read_statistics:true,upcoming:[],recent:[{name:'Campaign/?test',title:'<img src=x onerror=alert(1)>',delivered:null,click_rate:0,unsubscribed:0,skipped:2}]};
    page.renderRows();
    const rows=html.get('.ms-recent');
    assert.ok(rows.includes('&lt;img'));
    assert.ok(!rows.includes('<img'));
    assert.ok(rows.includes('Unavailable'));
    assert.ok(rows.includes('0%'));
    assert.ok(rows.includes('campaign=Campaign%2F%3Ftest'));
});

test('Start blocks creation actions without permission and opens a fresh Studio session when allowed',()=>{
    const {page,routes}=setup();
    page.data={actions:{email:false}};
    page.create('email');
    assert.equal(routes.length,0);
    page.data.actions.email=true;
    page.create('email');
    assert.equal(routes[0][0],'email-campaign-studio');
    assert.ok(routes[0][1].new);
});
