const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function composer() {
	const messages = [], routes = [];
	const context = {clearTimeout, setTimeout, frappe: {pages: {'email-campaign-studio': {}}, msgprint: text => messages.push(text),
		show_alert() {}, set_route: (...route) => routes.push(route)}, __: text => text};
	vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../finbyzreach/finbyzreach/page/email_campaign_studio/email_campaign_studio.js'), 'utf8') + '\nglobalThis.Studio = EmailCampaignStudio;', context);
	const studio = Object.create(context.Studio.prototype);
	Object.assign(studio, {wizardStep: 'what', wizardUsage: 'segment', editable: true,
		contentForm: {get_value: name => ({campaign_title: 'Newsletter', subscription_topic: 'News', email_template: 'Winter'})[name]},
		renderWizard() {}, showTemplateState() {}, checkCampaignTitle: async () => true, loadWizardDesign: async () => true});
	return {studio, messages, routes, frappe: context.frappe};
}

test('Back and Next preserve audience, content and delivery objects; workflow skips audience/time', async () => {
	const {studio} = composer();
	studio.scheduleForm = {batch_size: 100}; studio.filters = [['Contact', 'email_id', 'is', 'set']];
	const content = studio.contentForm, schedule = studio.scheduleForm, filters = studio.filters;
	await studio.advanceWizard(); assert.equal(studio.wizardStep, 'design');
	await studio.moveWizard(-1); assert.equal(studio.wizardStep, 'what');
	assert.equal(studio.contentForm, content); assert.equal(studio.scheduleForm, schedule); assert.equal(studio.filters, filters);
	studio.wizardUsage = 'workflow';
	await studio.advanceWizard(); await studio.advanceWizard();
	assert.equal(studio.wizardStep, 'check');
	await studio.moveWizard(-1); assert.equal(studio.wizardStep, 'design');
});

test('missing setup fields do not advance or mount a designer', async () => {
	const {studio, messages} = composer();
	studio.contentForm.get_value = () => '';
	studio.loadWizardDesign = () => { throw Error('Should not load'); };
	await studio.advanceWizard(); assert.equal(studio.wizardStep, 'what'); assert.equal(messages.length, 1);
});

test('failed designer save blocks both forward and backward navigation and draft creation', async () => {
	const {studio} = composer(); studio.wizardStep = 'design'; studio.wizardTemplate = 'Winter';
	studio.wizardFrame = {contentWindow: {finbyzEmailBuilder: {templateName: 'Winter', save: async () => false}}};
	studio.createCampaign = () => { throw Error('Cannot save stale content'); };
	await studio.advanceWizard(); assert.equal(studio.wizardStep, 'design');
	await studio.moveWizard(-1); assert.equal(studio.wizardStep, 'design');
	await studio.saveWizardDraft(); assert.equal(studio.wizardStep, 'design');
});

test('unloaded or mismatched designer cannot silently pass the save check', async () => {
	const {studio} = composer(); studio.wizardTemplate = 'Winter';
	studio.wizardFrame = {contentWindow: {}}; assert.equal(await studio.flushWizardDesign(), false);
	studio.wizardFrame.contentWindow.finbyzEmailBuilder = {templateName: 'Other', save: async () => true};
	assert.equal(await studio.flushWizardDesign(), false);
});

test('double Next while audience preview is pending runs only one preview and advances one step', async () => {
	const {studio} = composer(); studio.wizardStep = 'who';
	let resolve, calls = 0;
	studio.previewAudience = () => { calls++; return new Promise(done => { resolve = done; }); };
	const first = studio.advanceWizard(); await studio.advanceWizard();
	studio.preview = {eligible_count: 20}; resolve(); await first;
	assert.equal(calls, 1); assert.equal(studio.wizardStep, 'when');
});

test('audience with no eligible records stays on Who', async () => {
	const {studio} = composer(); studio.wizardStep = 'who';
	studio.previewAudience = async () => { studio.preview = {eligible_count: 0}; };
	await studio.advanceWizard(); assert.equal(studio.wizardStep, 'who');
});

test('segment final action reuses scheduling preflight; workflow saves email without creating a campaign', async () => {
	const {studio, routes} = composer(); studio.wizardStep = 'check';
	let reviewed = 0;
	studio.reviewAndSchedule = () => { reviewed++; };
	await studio.advanceWizard(); assert.equal(reviewed, 1);
	studio.wizardUsage = 'workflow';
	studio.createCampaign = () => { throw Error('Workflow must not schedule'); };
	await studio.advanceWizard(); assert.equal(reviewed, 1); assert.deepEqual(routes, [['List', 'Email Template']]);
});


test('sender is a separate campaign step and requires its own fields', async () => {
    const {studio} = composer();
    assert.deepEqual(Array.from(studio.wizardSteps()), ['what', 'design', 'sender', 'who', 'when', 'check']);
    studio.wizardStep = 'design';
    await studio.advanceWizard();
    assert.equal(studio.wizardStep, 'sender');
    studio.formValues = () => null;
    await studio.advanceWizard();
    assert.equal(studio.wizardStep, 'sender');
    studio.formValues = () => ({email_account: 'Outbound'});
    await studio.advanceWizard();
    assert.equal(studio.wizardStep, 'who');
});

test('a duplicate campaign title allows Design editing but blocks progression past Design', async () => {
    const {studio} = composer();
    studio.checkCampaignTitle = async () => false;
    await studio.advanceWizard();
    assert.equal(studio.wizardStep, 'design');
    await studio.advanceWizard();
    assert.equal(studio.wizardStep, 'design');
});

test('title checks ignore stale responses after typing or switching routes', async () => {
    const {studio, frappe} = composer();
    let title = 'First', resolve;
    const states = [];
    studio.contentForm.get_field = () => ({$input: {val: () => title}});
    studio.routeKey = 'new:1';
    studio.showCampaignTitleState = state => states.push(state);
    delete studio.checkCampaignTitle;
    frappe.call = () => new Promise(done => { resolve = done; });
    const pending = studio.checkCampaignTitle();
    title = 'Second';
    resolve({message: {available: false}});
    assert.equal(await pending, false);
    assert.deepEqual(states, ['checking']);
    const staleRoute = studio.checkCampaignTitle();
    studio.routeKey = 'new:2';
    resolve({message: {available: false}});
    assert.equal(await staleRoute, false);
    assert.deepEqual(states, ['checking', 'checking']);
    frappe.call = async () => ({message: {available: true}});
    assert.equal(await studio.checkCampaignTitle(), true);
    assert.equal(states.at(-1), 'available');
    frappe.call = async () => { throw Error('Offline'); };
    assert.equal(await studio.checkCampaignTitle(), false);
    assert.equal(states.at(-1), 'error');
});


test('a previously reached fourth step can be revisited directly from What', async () => {
    const {studio} = composer();
    studio.wizardStep = 'who';
    studio.wizardProgress = {segment: 3, workflow: 0};
    await studio.goToWizardStep('what');
    assert.equal(studio.wizardStep, 'what');
    await studio.goToWizardStep('who');
    assert.equal(studio.wizardStep, 'who');
    assert.equal(studio.wizardProgress.segment, 3);
});

test('unreached steps cannot be selected and campaign progress does not unlock workflow steps', async () => {
    const {studio} = composer();
    await studio.goToWizardStep('who');
    assert.equal(studio.wizardStep, 'what');
    studio.wizardProgress = {segment: 5, workflow: 0};
    studio.wizardUsage = 'workflow';
    await studio.goToWizardStep('check');
    assert.equal(studio.wizardStep, 'what');
});

test('direct revisits save pending designer changes and refuse failed saves', async () => {
    const {studio} = composer();
    studio.wizardStep = 'design';
    studio.wizardProgress = {segment: 3, workflow: 0};
    let saves = 0;
    studio.flushWizardDesign = async () => { saves++; return false; };
    await studio.goToWizardStep('who');
    assert.equal(studio.wizardStep, 'design');
    assert.equal(saves, 1);
    studio.flushWizardDesign = async () => { saves++; return true; };
    await studio.goToWizardStep('who');
    assert.equal(studio.wizardStep, 'who');
    assert.equal(saves, 2);
});

test('revisiting Design mounts the currently selected template', async () => {
    const {studio} = composer();
    studio.wizardStep = 'who';
    studio.wizardProgress = {segment: 3, workflow: 0};
    let loads = 0;
    studio.loadWizardDesign = async () => { loads++; return true; };
    await studio.goToWizardStep('design');
    assert.equal(studio.wizardStep, 'design');
    assert.equal(loads, 1);
});

test('a missing unsubscribe link is informational and does not block entering Design', async () => {
    const {studio, frappe} = composer();
    let setup = 0;
    studio.consentPolicyEnabled = true;
    studio.configureEmailSetup = async () => { setup++; return {message: {updated: false}}; };
    const warnings = [];
    studio.templateStateRequest = 1;
    studio.contentForm.get_field = () => ({$wrapper: {find: () => ({html: value => warnings.push(value)})}});
    studio.$root = {find: () => ({html: value => warnings.push(value)})};
    frappe.utils = {escape_html: value => value};
    frappe.call = async () => ({message: {has_unsubscribe: false}});
    await studio.showUnsubscribeWarning('Winter', 1);
    assert.ok(warnings[0].includes('Continue to Design'));
    assert.ok(warnings[1].includes('Add an Unsubscribe link block'));
    await studio.advanceWizard();
    assert.equal(studio.wizardStep, 'design');
    assert.equal(setup, 1);
});

test('a route change during a direct jump cannot navigate the replacement campaign', async () => {
    const {studio} = composer();
    studio.wizardStep = 'design';
    studio.wizardProgress = {segment: 3, workflow: 0};
    studio.routeKey = 'old';
    studio.checkCampaignTitle = async () => true;
    studio.flushWizardDesign = async () => { studio.routeKey = 'new'; studio.wizardStep = 'what'; return true; };
    await studio.goToWizardStep('who');
    assert.equal(studio.wizardStep, 'what');
});


test('unsubscribe guidance clears after adding the link and ignores stale template responses', async () => {
    const {studio, frappe} = composer();
    const warnings = [];
    studio.templateStateRequest = 1;
    studio.contentForm.get_field = () => ({$wrapper: {find: () => ({html: value => warnings.push(value)})}});
    studio.$root = {find: () => ({html: value => warnings.push(value)})};
    frappe.utils = {escape_html: value => value};
    frappe.call = async () => ({message: {has_unsubscribe: true}});
    await studio.showUnsubscribeWarning('Winter', 1);
    assert.deepEqual(warnings, ['', '']);
    await studio.showUnsubscribeWarning('Old email', 1);
    await studio.showUnsubscribeWarning('Winter', 0);
    assert.deepEqual(warnings, ['', '']);
});
