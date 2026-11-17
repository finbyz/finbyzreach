const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function routerWithGuard() {
    // Frappe's own conversion for the "form" view, as in frappe/router.js.
    const router = {
        routes: {form: {doctype: 'Form'}, user: {doctype: 'User'}, 'sales-order': {doctype: 'Sales Order'}},
        slug: name => name.toLowerCase().replace(/ /g, '-'),
        convert_from_standard_route(route) {
            const view = route[0] ? route[0].toLowerCase() : '';
            if (view === 'form') return [this.slug(route[1]), ...(route[2] ? [route[2]] : [])];
            return route;
        },
    };
    const context = {window: {frappe: {router}}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/form_route_guard.js'), 'utf8'), context);
    return router;
}

test('the Forms list path no longer throws', () => {
    const router = routerWithGuard();
    assert.deepEqual(router.convert_from_standard_route(['form']), ['form']);
    assert.deepEqual(router.convert_from_standard_route(['form', 'view', 'list']), ['form', 'view', 'list']);
    assert.deepEqual(router.convert_from_standard_route(['form', 'p646cu70cq']), ['form', 'p646cu70cq']);
});

test('standard Form routes for other DocTypes are unchanged', () => {
    const router = routerWithGuard();
    assert.deepEqual(router.convert_from_standard_route(['Form', 'Sales Order', 'SO-1']), ['sales-order', 'SO-1']);
    assert.deepEqual(router.convert_from_standard_route(['form', 'User', 'admin']), ['user', 'admin']);
});

test('the guard is installed once', () => {
    const router = routerWithGuard();
    const first = router.convert_from_standard_route;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../finbyzreach/public/js/form_route_guard.js'), 'utf8'), {window: {frappe: {router}}});
    assert.equal(router.convert_from_standard_route, first);
});
