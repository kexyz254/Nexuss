const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/nexuss/ui/app.js', 'utf8');
function load(context, ...names) {
  for (const name of names) {
    const match = source.match(new RegExp(`(?:async )?function ${name}\\([\\s\\S]*?\\n}`, 'm'));
    assert.ok(match, name);
    vm.runInContext(match[0], context);
  }
}
function node() {
  return { disabled: false, children: [], dataset: {}, style: {},
    append(...items) { this.children.push(...items); },
    setAttribute(k,v) { this[k] = v; }, removeAttribute(k) { delete this[k]; },
    focus() {}, scrollIntoView() {}, remove() { this.removed = true; },
  };
}
function harness() {
  const messages = [], storage = new Map();
  const controls = ['send','input','voice','archiveAttach','archiveRemove','newChat',
    'approve','reject','rollback','form','note','timeline'];
  const c = vm.createContext({
    console, AbortController, AbortSignal, Set, Promise,
    elements: Object.fromEntries(controls.map(k => [k,node()])),
    document: { createElement: node, createTextNode: s => s, querySelector: () => null },
    sessionId: 'session', activeConversationId: 'conversation',
    chatTurnLocked: true, followedChatTaskId: null, approvalRequestPending: false,
    terminalChatTaskStates: new Set(['completed','partially_completed','failed','denied','rolled_back']),
    sessionStorage: { setItem: (k,v)=>storage.set(k,v), getItem:k=>storage.get(k), removeItem:k=>storage.delete(k) },
    apiHeaders: () => ({}), titleCase: s => s,
    addMessage: (...m) => messages.push(m), renderTask: t => { c.currentTask = t; },
    showApproval: async a => { c.approvals.push(a.approval_id); }, approvals: [],
    hideApproval() {}, fetchReceipt: async () => ({ verified: true }),
    rememberUnifiedInteraction() {}, renderUnifiedInteraction() {},
    refreshConversationList() {}, refreshRuntimeBuildIdentity() {},
    setTimeout: fn => { queueMicrotask(fn); return 1; }, clearTimeout() {},
    showToast() {}, stopSpeaking() {}, nexussUnifiedTurnPromise: null,
  });
  load(c, 'chatTurnInProgress', 'retainChatFollow', 'clearChatFollow', 'setBusy',
    'coreTaskDisplayText', 'followUpdateRestart', 'followCoreTaskLifecycle');
  return { c, messages, storage };
}
function response(data, status=200) { return {ok:status===200,status,json:async()=>data}; }
function serveTasks(c, tasks, extra=()=>null) {
  let reads=0;
  c.fetch = async url => {
    const override = extra(url); if (override) return override;
    if (url.endsWith('/status')) return response({phase:'executing',progress_percent:25});
    if (url.includes('/engineering/')) return response({},404);
    if (url.includes('/refresh')) return response({display_text:'Verified final report'});
    const task = tasks[Math.min(reads++,tasks.length-1)];
    if (task instanceof Error) throw task;
    return response({task_id:'task', events:[], ...task});
  };
  return () => reads;
}

test('turn stays locked through awaited execution and rejects duplicate submission', async()=>{
  const {c,messages}=harness(); c.chatTurnLocked=false;
  load(c,'submitUnifiedUserTurn');
  let finish; let executions=0;
  c.executeInstruction=async()=>{executions++; await new Promise(r=>finish=r);};
  const pending=c.submitUnifiedUserTurn('update','text');
  await Promise.resolve();
  assert.equal(c.elements.input.disabled,true);
  const duplicate=c.submitUnifiedUserTurn('again','text');
  assert.equal(executions,1); assert.equal(messages.length,1);
  c.setBusy(false); assert.equal(c.elements.input.disabled,true);
  finish(); await pending; await duplicate;
  assert.equal(c.elements.input.disabled,false);
  assert.equal(c.chatTurnLocked,false);
});

test('approval unlocks only decision controls and follows to a single final report',async()=>{
  const {c,messages,storage}=harness();
  serveTasks(c,[{state:'awaiting_approval',approval:{approval_id:'a'}},
    {state:'awaiting_approval',approval:{approval_id:'a'}},{state:'executing'},
    {state:'verifying'},{state:'completed'}]);
  await c.followCoreTaskLifecycle({core_task_id:'task',interaction_id:'interaction'},'conversation');
  assert.equal(c.elements.input.disabled,true);
  assert.equal(c.elements.approve.disabled,false);
  assert.deepEqual(c.approvals,['a']);
  assert.equal(messages.length,1); assert.equal(messages[0][1],'Verified final report');
  assert.equal(storage.size,0);
});

for(const state of ['failed','denied','rolled_back','partially_completed']) {
  test(`${state} ends following and reports once`,async()=>{
    const {c,messages}=harness();const reads=serveTasks(c,[{state}]);
    await c.followCoreTaskLifecycle({core_task_id:'task'},'conversation');
    assert.equal(reads(),1);assert.equal(messages.length,1);assert.equal(messages[0][2],true);
  });
}

test('transient disconnect reconnects to the same task without submitting an action',async()=>{
  const {c,messages}=harness(); const reads=serveTasks(c,[new Error('offline'),{state:'executing'},{state:'completed'}]);
  await c.followCoreTaskLifecycle({core_task_id:'task'},'conversation');
  assert.equal(reads(),3); assert.equal(messages.length,1);
});

test('persistent outage reports unknown status and retains the task for reload',async()=>{
  const {c,messages,storage}=harness();const reads=serveTasks(c,[new Error('offline')]);
  await c.followCoreTaskLifecycle({core_task_id:'task'},'conversation');
  assert.equal(reads(),40);assert.equal(messages.length,1);
  assert.match(messages[0][1],/may still be running/);assert.equal(storage.size,1);
});

test('update acceptance does not finish before exact running SHA and retained result match',async()=>{
  const {c,messages}=harness(); const target='a'.repeat(40); let updateReads=0;
  serveTasks(c,[{state:'completed',plan:{steps:[{capability_id:'system.update.apply',parameters:{expected_target_sha:target}}]}}],url=>{
    if(!url.includes('update-result'))return null;
    updateReads++;
    assert.equal(messages.length,0);
    return response({status:'completed',target_sha:target,active_sha:target,
      running_sha:updateReads===1?'old':target});
  });
  await c.followCoreTaskLifecycle({core_task_id:'task'},'conversation');
  assert.equal(updateReads,2);assert.equal(messages.length,1);
  assert.match(messages[0][1],/restarted runtime is running aaaaaaaaaaaa/);
});

test('rollback cannot become successful update completion',async()=>{
  const {c}=harness();c.fetch=async()=>response({target_sha:'target',status:'rolled_back',detail:'Health failed'});
  const result=await c.followUpdateRestart('target',node(),node());
  assert.equal(result.ok,false);assert.match(result.text,/rolled back/);
});

test('stale update record cannot verify another target',async()=>{
  const {c}=harness();c.fetch=async()=>response({target_sha:'old',status:'completed',active_sha:'old',running_sha:'old'});
  const result=await c.followUpdateRestart('new',node(),node());
  assert.equal(result.ok,false); assert.equal(result.unresolved,true);
});

test('approval handler keeps the existing follower and never emits an Executing final answer',async()=>{
  const {c,messages}=harness();load(c,'decideApproval');
  c.currentTask={task_id:'task',approval:{approval_token:'token',approval_id:'a',payload_sha256:'hash'}};
  c.followedChatTaskId='task';
  let posts=0;c.fetch=async(url,opts)=>{posts++;assert.equal(opts.method,'POST');return response({task_id:'task',state:'executing'});};
  await c.decideApproval('approve');
  assert.equal(posts,1);assert.equal(messages.length,0);
  assert.equal(c.elements.input.disabled,true);assert.equal(c.approvalRequestPending,false);
});

test('refresh resumes the retained task without resubmitting the action',async()=>{
  const {c,storage}=harness();load(c,'resumeRetainedChatTask');
  c.retainChatFollow({core_task_id:'task',interaction_id:'i'},'conversation');
  c.chatTurnLocked=false;
  c.selectPersistentConversation=async id=>{c.activeConversationId=id;};
  let followed=0;c.followCoreTaskLifecycle=async i=>{followed++;assert.equal(i.core_task_id,'task');};
  await c.resumeRetainedChatTask();
  assert.equal(followed,1);assert.equal(c.elements.input.disabled,false);
});

test('unified action awaits lifecycle and suppresses provisional static response',async()=>{
  const {c,messages}=harness();load(c,'executeUnifiedInteraction');
  c.isP610DLocalMediaCommand=()=>false;
  c.ensurePersistentConversation=async()=>{};
  c.crypto={randomUUID:()=> 'request'};
  c.observeInteractionProgress=()=>()=>{};
  c.updateConversationHeader=()=>{};
  c.p610DFetchPresentation=async()=>({});
  c.p610DPresentCoreTask=async()=>({presented:true});
  c.fetch=async()=>response({kind:'action',core_task_id:'task',core_task_state:'executing',display_text:'Executing',conversation:{}});
  let resolveFollow;c.followCoreTaskLifecycle=()=>new Promise(r=>resolveFollow=r);
  let finished=false;const run=c.executeUnifiedInteraction('update','text').then(()=>{finished=true;});
  await new Promise(setImmediate);
  assert.equal(finished,false);assert.equal(messages.length,0);
  assert.equal(c.elements.input.disabled,true);
  resolveFollow();await run;
});

test('ordinary action decision summaries are visible before a final response',async()=>{
  const {c}=harness(); load(c,'observeInteractionProgress');
  const timers=[];c.setTimeout=fn=>{timers.push(fn);return timers.length;};
  c.fetch=async()=>response({state:'running',events:[
    {sequence:1,event_type:'route_selected',state:'running',detail:'Selected update inspection'},
    {sequence:2,event_type:'capability_dispatch_started',state:'executing',detail:'Checking the approved branch'},
  ]});
  const stop=c.observeInteractionProgress('request','conversation');
  await timers.shift()();
  const panel=c.elements.timeline.children[0];
  assert.equal(panel.hidden,false);
  assert.equal(panel.children[1].children.length,2);
  assert.match(panel.children[1].children[1].textContent,/Checking the approved branch/);
  stop({events:[],state:'completed'});
  assert.equal(panel.dataset.state,'finished');
});

test('optional telemetry outage does not prevent authoritative terminal reporting',async()=>{
  const {c,messages}=harness();
  serveTasks(c,[{state:'completed'}],url=>url.endsWith('/status')?Promise.reject(new Error('telemetry down')):null);
  await c.followCoreTaskLifecycle({core_task_id:'task'},'conversation');
  assert.equal(messages.length,1);assert.match(messages[0][1],/completed/);
});

test('pending task rendering tolerates a missing final receipt',()=>{
  const {c}=harness();load(c,'renderReceipt');
  for(const key of ['receiptId','receiptVersion','receiptVerified','receiptReversible','receiptTitle','copyPath'])c.elements[key]=node();
  c.renderReceipt(null);
  assert.equal(c.elements.receiptVerified.textContent,'Pending');
  assert.equal(c.elements.rollback.hidden,true);
});
