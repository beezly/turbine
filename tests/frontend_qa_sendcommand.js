// Finite, offline QA harness for templates/index.html's sendCommand().
// No browser, no server: extracts the function source via regex and runs
// it in a vm sandbox with mocked window/document/socket.
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync('templates/index.html', 'utf8');
const m = html.match(/function sendCommand\(command\) \{[\s\S]*?\n        \}/);
if (!m) { console.error('FAIL: could not locate sendCommand()'); process.exit(1); }
const fnSrc = m[0];

function run(promptReturn, controlAvailable, confirmReturn) {
  const emits = [];
  const feedbacks = [];
  const sandbox = {
    window: { prompt: () => promptReturn, confirm: () => confirmReturn },
    socket: { emit: (...args) => emits.push(args) },
    setFeedback: (kind, text) => feedbacks.push([kind, text]),
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(fnSrc + "\nthis.controlAvailable = " + controlAvailable + ";", sandbox);
  vm.runInContext('sendCommand("start")', sandbox);
  return { emits, feedbacks };
}

let failures = 0;
function check(label, cond) {
  if (!cond) { console.error('FAIL:', label); failures++; }
  else console.log('ok:', label);
}

// 1. Control unavailable -> never prompts, never emits.
{
  const { emits, feedbacks } = run('ignored', false, true);
  check('control-disabled: no emit', emits.length === 0);
  check('control-disabled: error feedback', feedbacks.some(f => f[0] === 'err'));
}

// 2. User cancels confirm dialog -> no prompt reached, no emit.
{
  const { emits } = run('ignored', true, false);
  check('confirm-cancelled: no emit', emits.length === 0);
}

// 3. User confirms, then cancels password prompt (returns null) -> no emit.
{
  const { emits } = run(null, true, true);
  check('password-prompt-cancelled: no emit', emits.length === 0);
}

// 4. User confirms, submits empty password -> no emit, error feedback.
{
  const { emits, feedbacks } = run('', true, true);
  check('empty-password: no emit', emits.length === 0);
  check('empty-password: error feedback', feedbacks.some(f => f[0] === 'err' && /required/.test(f[1])));
}

// 5. User confirms, supplies password -> emits dict {command, password}, never a bare string.
{
  const { emits } = run('s3cr3t', true, true);
  check('password-supplied: exactly one emit', emits.length === 1);
  const [event, payload] = emits[0] || [];
  check('password-supplied: event name', event === 'command');
  check('password-supplied: payload is dict not bare string', typeof payload === 'object' && payload !== null);
  check('password-supplied: command field', payload && payload.command === 'start');
  check('password-supplied: password field matches', payload && payload.password === 's3cr3t');
}

// 6. Password value never appears in the function source itself (no stray console/log echoing it elsewhere).
check('source has no console.log of password var', !/console\.(log|warn|error)\([^)]*password/.test(fnSrc));
check('source has no localStorage.setItem/getItem call', !/localStorage\.(setItem|getItem)/.test(fnSrc));

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
