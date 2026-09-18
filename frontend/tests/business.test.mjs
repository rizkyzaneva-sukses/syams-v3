import test from 'node:test';
import assert from 'node:assert/strict';
import {canAccess, flowGates, normalizeDates, orderWip} from '../src/business.js';
import {requestPayload} from '../src/api.js';

test('route roles do not grant CEO an operational CMO page by implication', () => {
  assert.equal(canAccess('CEO', '/cmo/orders'), false);
  assert.equal(canAccess('CEO', '/cfo/shipments'), true);
  assert.equal(canAccess('CMO_SUPPORT', '/cfo/invoices'), false);
  assert.equal(canAccess('CMO_SUPPORT', '/coo/deliveries'), false);
  assert.equal(canAccess('CMO_MANAGER', '/coo/deliveries'), true);
  assert.equal(canAccess('CMO_MANAGER', '/cfo/shipments'), true);
  assert.equal(canAccess('CMO_SUPPORT', '/cfo/shipments'), false);
  assert.equal(canAccess('CMO_SUPPORT', '/coo/closing'), false);
});

test('blank optional dates are sent as null', () => {
  assert.deepEqual(
    normalizeDates({due_date: '', notes: '', nested: {valid_until: ''}}),
    {due_date: null, notes: '', nested: {valid_until: null}},
  );
});

test('update payloads omit server-owned and immutable route fields', () => {
  assert.deepEqual(
    requestPayload('/cmo/quotations/4', 'PATCH', {id: 4, created_at: 'x', quotation_no: 'Q-4', order_fk: 9, amount: 200, valid_until: ''}),
    {amount: 200, valid_until: null},
  );
  assert.deepEqual(
    requestPayload('/coo/movements/3', 'PATCH', {id: 3, article_id: 7, process: 'Cutting', qty_done: 2}),
    {qty_done: 2},
  );
});

test('flow gates and WIP use server field names and quantities', () => {
  const gates = flowGates({
    current_step: 'INVOICE',
    progress: {steps: [{key: 'ORDER', label: 'Order', gate: 'CMO'}, {key: 'INVOICE', label: 'Invoice', gate: 'CFO'}, {key: 'SAMPLE', label: 'Sample', gate: 'SAMPLE_PIC'}]},
    next_steps: [{step: 'SAMPLE', can_advance: true, authorized: true}],
  });
  assert.equal(gates.find(g => g.step === 'ORDER').status, 'completed');
  assert.equal(gates.find(g => g.step === 'SAMPLE').status, 'ready');
  assert.equal(gates.find(g => g.step === 'SAMPLE').canAdvance, true);

  const rows = orderWip([{id: 1, order_id: 'SO-1', buyer: 'Buyer', articles: [{id: 10}]}], [{article_id: 10, process: 'Cutting', qty_in: 20, qty_done: 12, qty_reject: 3, status: 'IN_PROCESS'}]);
  assert.deepEqual(rows, [{order_id: 'SO-1', buyer: 'Buyer', totalWIP: 5, processes: [{process: 'Cutting', wip: 5, status: 'IN_PROCESS'}]}]);
});
