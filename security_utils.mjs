/** Best-effort local stats and privacy-preserving diagnostic events. */
import {createHash, randomUUID} from 'node:crypto';

const digest = value => createHash('sha256').update(String(value)).digest('hex');
const safeNumberFields = new Set([
  'candidates','steps','slow_requests_at_boundary','slow_sequence_before',
  'slow_sequence_after','threshold_tokens','native_receipt_count',
  'graphsAuthored','substitutions','slowCalls','code',
]);
const safeBooleanFields = new Set(['valid_substitution','activated','certified_substitution']);

/** No raw prompts, tool arguments, stdout/stderr, provider replies or exception text. */
export function safeAuditEvent(id, event) {
  const name = typeof event?.kind === 'string' && /^[a-z0-9_./-]{1,100}$/i.test(event.kind)
    ? event.kind : 'unknown';
  const result = {time: Date.now(), session_sha256: digest(id), kind: name};
  for (const [key, value] of Object.entries(event ?? {})) {
    if (/(?:_sha256|_hash)$/.test(key)
        && typeof value === 'string' && /^[a-f\d]{32,128}$/i.test(value)) {
      result[key] = value;
    } else if (safeNumberFields.has(key) && Number.isSafeInteger(value)) {
      result[key] = value;
    } else if (safeBooleanFields.has(key) && typeof value === 'boolean') {
      result[key] = value;
    }
  }
  return result;
}

/** Non-critical stats persistence must not crash agent turns on Windows EPERM. */
export function bestEffortStatsWrite(fs, statsPath, stats, warn = () => {}) {
  const tmp = statsPath + '.' + randomUUID() + '.tmp';
  try {
    fs.writeFileSync(tmp, JSON.stringify(stats, null, 2) + '\n', {mode:0o600});
    fs.renameSync(tmp, statsPath);
    return true;
  } catch (error) {
    warn(`HarnessMM statistics not saved (${error.code ?? 'unknown'})`);
    return false;
  } finally {
    // Never delete the existing target or non-atomically overwrite it.
    try { fs.rmSync(tmp, {force:true}); }
    catch (error) { warn(`HarnessMM temp cleanup failed: ${error.code ?? 'unknown'}`); }
  }
}
