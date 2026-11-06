const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function form({ legacy = false } = {}) {
    const pending = [];
    const hooks = {};
    class Element {
        constructor() { this.children = new Map(); this.value = undefined; }
        empty() { this.children.clear(); return this; }
        html() { return this; } on() { return this; } append() { return this; }
        prop() { return this; } remove() { return this; }
        find(selector) {
            if (!this.children.has(selector)) this.children.set(selector, new Element());
            const result = this.children.get(selector);
            if (selector === '.rs-match' && result.value === undefined) result.value = 'OR';
            return result;
        }
        val(value) { if (value !== undefined) { this.value = value; return this; } return this.value || ''; }
    }
    const root = new Element();
    const frappe = {
        model: { with_doctype: () => Promise.resolve() },
        utils: { escape_html: value => String(value), parse_json: JSON.parse },
        ui: {
            FilterGroup: class {
                constructor(options) { this.options = options; this.filters = []; }
                add_filters(filters) {
                    return new Promise(resolve => pending.push(() => {
                        this.filters = JSON.parse(JSON.stringify(filters));
                        this.options.on_change();
                        resolve();
                    }));
                }
                get_filters() { return this.filters; }
                toggle_empty_filters() {}
            },
            form: {
                on(doctype, handlers) { hooks[doctype] = handlers; },
                make_control({df}) {
                    return { df, value: [],
                        set_value(value) { return Promise.resolve().then(() => { this.value = value; df.onchange(); }); },
                        get_value() { return this.value; },
                    };
                },
            },
        },
    };
    const context = {frappe, __: text => text, $: () => new Element(), setTimeout: () => 1, clearTimeout() {}};
    const filename = path.join(__dirname, '../finbyzreach/finbyzreach/doctype/reach_segment/reach_segment.js');
    vm.runInNewContext(fs.readFileSync(filename, 'utf8') + '\nglobalThis.Builder = ReachSegmentBuilder;', context);
    context.Builder.prototype.load = () => {};
    context.Builder.prototype.actions = () => {};
    const filters = [['Contact','email_id','is','set']];
    const doc = {name:'Contact Segment',audience_doctype:'Contact',segment_type:'Static',
        filter_groups_json:JSON.stringify(legacy ? filters : [filters]),
        filter_expression_json:'',exclude_filters_json:'[]',exclude_segments_json:'["Other Segment"]'};
    let dirtyCalls = 0;
    const frm = {doc,perm:[{write:1}],toggle_display() {},get_field: () => ({$wrapper:root}),
        is_new: () => false,is_dirty: () => Boolean(doc.__unsaved),dirty() { dirtyCalls++; doc.__unsaved = 1; }};
    async function hydrate() {
        // VM and host promises settle on separate microtask queues.
        await new Promise(setImmediate);
        for (const finish of pending.splice(0)) finish();
        await frm.builder.initialized;
    }
    hooks['Reach Segment'].refresh(frm);
    return {frm,hooks:hooks['Reach Segment'],hydrate,dirtyCalls: () => dirtyCalls};
}

test('saved filters and excluded segments hydrate without dirtying the document', async () => {
    const state = form();
    const original = JSON.stringify(state.frm.doc);
    await state.hydrate();
    assert.equal(state.frm.builder.ready,true);
    assert.equal(state.dirtyCalls(),0);
    assert.equal(JSON.stringify(state.frm.doc),original);
    // Native controls may repeat their change event after painting.
    state.frm.builder.groups[0].filter.options.on_change();
    state.frm.builder.segmentExclusionControl.df.onchange();
    assert.equal(state.dirtyCalls(),0);
});

test('legacy flat filter arrays are not marked edited merely by opening the form', async () => {
    const state = form({legacy:true});
    const original = state.frm.doc.filter_groups_json;
    await state.hydrate();
    state.frm.builder.changed();
    assert.equal(state.dirtyCalls(),0);
    assert.equal(state.frm.doc.filter_groups_json,original);
});

test('real filter edits still mark dirty and serialize the new value', async () => {
    const state = form();
    await state.hydrate();
    const group = state.frm.builder.groups[0].filter;
    group.filters[0] = ['Contact','email_id','like','%@example.com'];
    group.options.on_change();
    assert.equal(state.dirtyCalls(),1);
    assert.equal(JSON.parse(state.frm.doc.filter_groups_json)[0][0][3],'%@example.com');
    group.options.on_change();
    assert.equal(state.dirtyCalls(),1);
});

test('real exclusion changes still mark dirty', async () => {
    const state = form();
    await state.hydrate();
    const control = state.frm.builder.segmentExclusionControl;
    control.value = ['Different Segment'];
    control.df.onchange();
    assert.equal(state.dirtyCalls(),1);
    assert.deepEqual(JSON.parse(state.frm.doc.exclude_segments_json),['Different Segment']);
});

test('refresh after save disposes old callbacks and stays saved', async () => {
    const state = form();
    await state.hydrate();
    const old = state.frm.builder;
    state.hooks.refresh(state.frm);
    await state.hydrate();
    old.groups[0].filter.filters[0][3] = 'stale value';
    old.groups[0].filter.options.on_change();
    assert.equal(old.disposed,true);
    assert.equal(state.dirtyCalls(),0);
    assert.equal(JSON.parse(state.frm.doc.filter_groups_json)[0][0][3],'set');
});

test('saving waits for filter hydration and does not serialize empty controls', async () => {
    const state = form();
    let validated = false;
    const saving = state.hooks.validate(state.frm).then(() => { validated = true; });
    await Promise.resolve();
    assert.equal(validated,false);
    await state.hydrate();
    await saving;
    assert.deepEqual(JSON.parse(state.frm.doc.filter_groups_json),[[['Contact','email_id','is','set']]]);
    assert.equal(state.dirtyCalls(),0);
});
