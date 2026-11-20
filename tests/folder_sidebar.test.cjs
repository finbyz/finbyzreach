const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(doctype='Reach Segment', {create=true, folders=true, read=true, write=true}={}) {
    const calls=[],html=new Map();
    let filters=[[doctype,'name','like','%search%'],[doctype,'owner','=','someone@example.invalid']];
    const root={closest(){return this;},addClass(){return this;},prependTo(){return this;},html(value){html.set('root',value);return this;},on(){return this;},find(key){return {html(value){html.set(key,value);return this;}};}};
    const frappe={reach_folder_sidebar:{},provide(){},utils:{escape_html:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),icon:()=>''},model:{can_read:dt=>dt===doctype?read:folders,can_create:()=>create,can_write:()=>write},
        call:async options=>{calls.push(JSON.parse(JSON.stringify(options)));return {message: options.method.endsWith('get_count')?3:[]};},
        prompt(fields,action){frappe.promptFields=fields;frappe.promptAction=action;},show_alert(){},set_route(){}};
    const list={doctype,page:{main:root,add_menu_item(){}},settings:{refresh(){list.nativeRefreshes=(list.nativeRefreshes||0)+1;}},start:100,on_filter_change(){this.filterChanges=(this.filterChanges||0)+1;},
        filter_area:{get:()=>filters,async clear(){filters=[];},async set(next){filters=JSON.parse(JSON.stringify(next));}},
        async refresh(){this.settings.refresh(this);}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../finbyzreach/public/js/folder_sidebar.js'),'utf8'),{frappe,__:text=>text,$:()=>root});
    frappe.reach_folder_sidebar.setup(list);
    return {frappe,list,sidebar:list.folder_sidebar,calls,html};
}

test('all three native lists use their own folder models with bounded children',async()=>{
    for(const [doctype,folder,field] of [['Reach Segment','Reach Segment Folder','folder'],['Email Template Master','Email Template Folder','folder'],['Email Template','Email Folder','custom_folder']]){
        const {sidebar,calls}=setup(doctype);
        await sidebar.reload();
        assert.equal(sidebar.config.folder,folder);
        assert.equal(sidebar.config.field,field);
        const query=calls.find(call=>call.args.doctype===folder);
        assert.equal(query.method,'frappe.client.get_list');
        assert.equal(query.type,'GET');
        assert.equal(query.args.limit_page_length,51);
    }
});

test('folder selection preserves search and other filters; unfiled uses native is not set',async()=>{
    const {sidebar,list}=setup();
    await sidebar.select('folder:Events');
    let filters=list.filter_area.get();
    assert.equal(filters.length,3);
    assert.deepEqual(filters[0],['Reach Segment','name','like','%search%']);
    assert.deepEqual(filters[2],['Reach Segment','folder','=','Events']);
    await sidebar.select('@without');
    assert.deepEqual(list.filter_area.get()[2],['Reach Segment','folder','is','not set']);
    assert.equal(sidebar.selected(),'@without');
    await sidebar.select('@all');
    assert.equal(list.filter_area.get().length,2);
    assert.equal(list.start,0);
});

test('Without Folder counts use the same native filter as selection for all three lists',async()=>{
    for(const doctype of ['Reach Segment','Email Template Master','Email Template']) {
        const {sidebar,list,calls}=setup(doctype);
        await sidebar.reload();
        await sidebar.select('@without');
        await sidebar.refresh();
        const selected=list.filter_area.get();
        const count=calls.filter(call=>call.method==='frappe.client.get_count').at(-1);
        assert.deepEqual(count.args.filters,selected);
        assert.equal(count.args.filters.at(-1)[2],'is');
        assert.equal(count.args.filters.at(-1)[3],'not set');
        await sidebar.select(`folder:${sidebar.config.root}`);
        assert.equal(sidebar.selected(),`folder:${sidebar.config.root}`);
    }
});

test('expanding and loading more uses independent bounded keyset cursors',async()=>{
    const {sidebar,frappe,calls}=setup();
    await sidebar.reload();
    frappe.call=async options=>{calls.push(JSON.parse(JSON.stringify(options)));return {message:options.args.doctype==='Reach Segment Folder'?
        (options.args.filters.length===1?Array.from({length:51},(_,i)=>({name:`F${String(i).padStart(3,'0')}`,folder_name:`Folder ${i}`})):[{name:'F050',folder_name:'Folder 50'}]):options.method.endsWith('get_count')?51:[]};};
    await sidebar.toggle('Parent');
    assert.equal(sidebar.branches.get('Parent').rows.length,50);
    assert.equal(sidebar.branches.get('Parent').more,true);
    await sidebar.load('Parent',true);
    assert.equal(sidebar.branches.get('Parent').rows.length,51);
    const query=calls.filter(call=>call.args.doctype==='Reach Segment Folder').at(-1);
    assert.deepEqual(query.args.filters,[['parent_reach_segment_folder','=','Parent'],['name','>','F049']]);
    assert.equal(sidebar.branches.get('Parent').more,false);
});

test('folder labels are escaped and folder names cannot collide with navigation keys',async()=>{
    const {sidebar}=setup();
    await sidebar.select('folder:@all');
    assert.equal(sidebar.selected(),'folder:@all');
    const html=sidebar.row('@all','<img src=x onerror="bad">',0,true);
    assert.ok(html.includes('data-select="folder:@all"'));
    assert.ok(html.includes('&lt;img'));
    assert.ok(!html.includes('<img'));
});

test('native read-only folder access hides create while preserving navigation',async()=>{
    const {sidebar,html,frappe,list}=setup('Email Template',{create:false});
    await sidebar.reload();
    assert.ok(!html.get('.reach-folder-footer').includes('data-action="new"'));
    assert.ok(html.get('.reach-folder-nav').includes('Without Folder'));
    const first=list.folder_sidebar;
    frappe.reach_folder_sidebar.setup(list);
    assert.equal(list.folder_sidebar,first);
    await list.refresh();
    assert.equal(list.nativeRefreshes,1);
});

test('new Email Template folder uses native insert in the selected parent',async()=>{
    const {sidebar,frappe,calls}=setup('Email Template');
    await sidebar.select('folder:Newsletter');
    sidebar.new_folder();
    assert.equal(frappe.promptFields[1].default,'Newsletter');
    await frappe.promptAction({folder_name:'  November  ',parent:'Newsletter'});
    const insert=calls.find(call=>call.method==='frappe.client.insert');
    assert.deepEqual(insert.args.doc,{doctype:'Email Folder',folder_name:'November',parent_email_folder:'Newsletter'});
});

test('folder counts are permission-aware grouped queries rather than one query per folder',async()=>{
    const {sidebar,calls}=setup();
    await sidebar.reload();
    sidebar.branches.set(sidebar.config.root,{rows:[{name:'Events',folder_name:'Events'},{name:'Partners',folder_name:'Partners'}]});
    const before=calls.length;
    await sidebar.refresh();
    assert.equal(calls.length-before,3);
    const grouped=calls.at(-1);
    assert.equal(grouped.method,'frappe.client.get_list');
    assert.equal(grouped.args.group_by,'folder');
    assert.deepEqual(grouped.args.fields,['folder',{COUNT:'name',as:'folder_count'}]);
    assert.deepEqual(grouped.args.filters.at(-1),['Reach Segment','folder','in',['Events','Partners']]);
});

test('no-read access does not mount a sidebar or send queries',()=>{
    const {sidebar,calls}=setup('Reach Segment',{read:false});
    assert.equal(sidebar,undefined);
    assert.equal(calls.length,0);
});


test('workflow folders load top-level null/empty parents and create valid nested paths', async () => {
    const {sidebar,frappe,list,calls}=setup('Automation Workflow');
    await sidebar.reload();
    assert.equal(sidebar.config.folder,'Automation Workflow Folder');
    const query=calls.find(call=>call.args.doctype==='Automation Workflow Folder');
    assert.deepEqual(query.args.filters[0],['parent_folder','is','not set']);
    await sidebar.select('@without');
    assert.deepEqual(list.filter_area.get().at(-1),['Automation Workflow','folder','is','not set']);
    sidebar.new_folder();
    assert.equal(frappe.promptFields.find(field=>field.fieldname==='parent').reqd,0);
    await frappe.promptAction({folder_name:'Newsletter',parent:'Marketing'});
    const insert=calls.find(call=>call.method==='frappe.client.insert');
    assert.equal(insert.args.doc.path,'Marketing/Newsletter');
    assert.equal(insert.args.doc.parent_folder,'Marketing');
});

test('workflow root folder creation supplies the existing path-based folder identity', async () => {
    const {sidebar,frappe,calls}=setup('Automation Workflow');
    sidebar.new_folder();
    await frappe.promptAction({folder_name:'Events',parent:''});
    const insert=calls.find(call=>call.method==='frappe.client.insert');
    assert.equal(insert.args.doc.path,'Events');
    assert.equal(insert.args.doc.parent_folder,null);
});

test('rename is available only for writable folders and never for system roots',async()=>{
    for (const doctype of ['Reach Segment','Email Template Master','Email Template','Automation Workflow','Form']) {
        const {sidebar}=setup(doctype);
        assert.ok(sidebar.row('Existing','Existing',0,true).includes('data-rename="Existing"'));
        assert.ok(!sidebar.row(sidebar.config.root,'Root',0,true).includes('data-rename='));
        assert.ok(!sidebar.row('@all','All').includes('data-rename='));
        const readonly=setup(doctype,{write:false});
        assert.ok(!readonly.sidebar.row('Existing','Existing',0,true).includes('data-rename='));
        readonly.sidebar.rename_folder('Existing');
        assert.equal(readonly.frappe.promptAction,undefined);
    }
});

test('rename uses the server permission-checked action and preserves active search/folder filters',async()=>{
    for (const doctype of ['Reach Segment','Email Template Master','Email Template','Automation Workflow','Form']) {
        const {sidebar,list,frappe,calls}=setup(doctype);
        await sidebar.reload();
        sidebar.branches.set(sidebar.config.root,{rows:[{name:'Existing',folder_name:'Existing'}]});
        await sidebar.select('folder:Existing');
        const originalCall=frappe.call;
        frappe.call=async options=>{
            if(options.method==='finbyzreach.folder_sidebar.rename_folder') {
                calls.push(options);
                return {message:{name:'Renamed',renamed_folders:{Existing:'Renamed'}}};
            }
            return originalCall(options);
        };
        sidebar.rename_folder('Existing');
        assert.equal(frappe.promptFields[0].default,'Existing');
        await frappe.promptAction({folder_name:' Renamed '});
        const rename=calls.find(call=>call.method==='finbyzreach.folder_sidebar.rename_folder');
        assert.equal(rename.type,'POST');
        assert.deepEqual(JSON.parse(JSON.stringify(rename.args)),{doctype:sidebar.config.folder,name:'Existing',new_name:'Renamed'});
        assert.deepEqual(list.filter_area.get(),[
            [doctype,'name','like','%search%'],[doctype,'owner','=','someone@example.invalid'],[doctype,sidebar.config.field,'=','Renamed']
        ]);
        assert.equal(list.start,0);
    }
});

test('renaming a workflow parent preserves the selected descendant and expanded branch',async()=>{
    const {sidebar,list,frappe}=setup('Automation Workflow');
    await sidebar.reload();
    sidebar.branches.set('',{rows:[{name:'Parent',folder_name:'Parent'}]});
    sidebar.expanded.add('Parent');
    await sidebar.select('folder:Parent/Child');
    const originalCall=frappe.call;
    frappe.call=async options=>options.method==='finbyzreach.folder_sidebar.rename_folder'
        ? {message:{name:'New',renamed_folders:{Parent:'New','Parent/Child':'New/Child'}}}
        : originalCall(options);
    sidebar.rename_folder('Parent');
    await frappe.promptAction({folder_name:'New'});
    assert.equal(sidebar.selected(),'folder:New/Child');
    assert.ok(sidebar.expanded.has('New'));
    assert.ok(sidebar.branches.has('New'));
    assert.equal(list.start,0);
});

test('a refused rename leaves the selection and branch cache untouched',async()=>{
    const {sidebar,list,frappe}=setup();
    await sidebar.reload();
    sidebar.branches.set(sidebar.config.root,{rows:[{name:'Existing',folder_name:'Existing'}]});
    await sidebar.select('folder:Existing');
    const before=JSON.stringify(list.filter_area.get());
    frappe.call=async()=>{throw Error('No permission');};
    sidebar.rename_folder('Existing');
    await assert.rejects(frappe.promptAction({folder_name:'Renamed'}),/No permission/);
    assert.equal(JSON.stringify(list.filter_area.get()),before);
    assert.equal(sidebar.branches.get(sidebar.config.root).rows[0].name,'Existing');
});
