const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

for (const [write, allowed] of [[false, true], [true, false], [true, true], [false, false]]) {
    test(`segment export follows native Export permission (write=${write}, export=${allowed})`, () => {
        const buttons = [];
        const context = {frappe: {
            model: {can_export: () => allowed, can_create: () => false},
            call: async () => ({message: null}),
            ui: {form: {on() {}}},
        }, __: text => text};
        const filename = path.join(__dirname, '../finbyzreach/finbyzreach/doctype/reach_segment/reach_segment.js');
        vm.runInNewContext(fs.readFileSync(filename, 'utf8') + '\nglobalThis.Builder = ReachSegmentBuilder;', context);
        const builder = Object.create(context.Builder.prototype);
        builder.frm = {doc: {segment_type:'Active'}, perm:[{write}], is_new:() => false,
            add_custom_button: (label, callback, group) => buttons.push({label, group})};
        builder.actions();
        assert.equal(buttons.filter(button => button.group === 'Export').length, allowed ? 2 : 0);
    });
}

for (const [audience, canCampaign, canWorkflow, archived, expected] of [
    ['Contact', true, true, 0, ['Send email', 'Use in workflow']],
    ['Opportunity', true, true, 0, ['Use in workflow']],
    ['Lead', false, false, 0, []],
    ['Lead', true, true, 1, []],
]) {
    test(`segment detail offers usage actions (${audience}, archived=${archived})`, () => {
        const buttons = [];
        const context = {frappe: {
            model: {can_export: () => false, can_create: doctype => doctype === 'Campaign' ? canCampaign : canWorkflow},
            call: async () => ({message: null}),
            ui: {form: {on() {}}},
        }, __: text => text};
        const filename = path.join(__dirname, '../finbyzreach/finbyzreach/doctype/reach_segment/reach_segment.js');
        vm.runInNewContext(fs.readFileSync(filename, 'utf8') + '\nglobalThis.Builder = ReachSegmentBuilder;', context);
        const builder = Object.create(context.Builder.prototype);
        builder.frm = {doc: {name: 'S', segment_type: 'Active', audience_doctype: audience, archived}, perm: [{write: false}],
            is_new: () => false, add_custom_button: label => buttons.push(label)};
        builder.actions();
        assert.deepEqual(buttons.filter(label => ['Send email', 'Use in workflow'].includes(label)), expected);
    });
}
