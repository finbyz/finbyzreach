const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
    let route=['email-template-builder','Newsletter / DE','Email Template'];
    let dirty=false, writes=0, confirmation;
    const frame={contentWindow:{dispatchEvent:()=>!dirty},addEventListener(){},set src(value){this.url=value; writes++;},get src(){return this.url;}};
    const page={main:{addClass(){},append(){}},set_title(){},set_breadcrumbs(){},set_secondary_action(){}};
    const frappe={pages:{'email-template-builder':{}},ui:{make_app_page:()=>page},get_route:()=>route,set_route(){},confirm(message,yes,no){confirmation={yes,no};}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../finbyzreach/email_template_builder/page/email_template_builder/email_template_builder.js'),'utf8'),{frappe,document:{createElement:()=>frame},URLSearchParams,Event,__:x=>x});
    const wrapper={};
    const handlers=frappe.pages['email-template-builder'];
    handlers.on_page_load(wrapper);
    return {show:()=>handlers.on_page_show(wrapper),frame,setRoute:value=>route=value,setDirty:value=>dirty=value,writes:()=>writes,confirmation:()=>confirmation};
}

test('Desk builder encodes document identity and keeps the existing editor when returning',()=>{
    const ctx=setup();ctx.show();
    const url=new URL(ctx.frame.src,'http://localhost');
    assert.equal(url.pathname,'/builder');
    assert.equal(url.searchParams.get('template'),'Newsletter / DE');
    assert.equal(url.searchParams.get('template_doctype'),'Email Template');
    ctx.show();assert.equal(ctx.writes(),1);
});

test('switching to another document waits for confirmation if the React editor reports unsaved edits',()=>{
    const ctx=setup();ctx.show();ctx.setDirty(true);
    ctx.setRoute(['email-template-builder','Master A','Email Template Master']);ctx.show();
    assert.equal(ctx.writes(),1);
    assert.ok(ctx.confirmation());
    ctx.confirmation().yes();
    assert.equal(ctx.writes(),2);
    assert.equal(new URL(ctx.frame.src,'http://localhost').searchParams.get('template_doctype'),'Email Template Master');
});
