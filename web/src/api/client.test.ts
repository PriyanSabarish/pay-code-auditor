import { describe, expect, it } from 'vitest';
import { fileError, parseError, pollInterval, safeSource } from './client';

describe('HTTP boundary',()=>{
  it('maps FastAPI validation errors to upload fields',()=>{
    const error=parseError({detail:[{loc:['body','paycodes'],msg:'Column missing'},{loc:['body','award_id'],msg:'Choose an award'}]},422);
    expect(error.fields).toEqual({paycodes:'Column missing',award_id:'Choose an award'});
  });
  it('preserves readable errors and handles unexpected responses',()=>{
    expect(parseError({detail:'Audit expired'},404).message).toBe('Audit expired');
    expect(parseError('<html>proxy failed</html>',502).message).toContain('502');
  });
  it('polls only active jobs',()=>{
    expect(pollInterval('running')).toBe(1000);
    expect(pollInterval('queued')).toBe(1000);
    for(const status of ['complete','failed','awaiting_input'] as const)expect(pollInterval(status)).toBe(false);
  });
  it('rejects unsafe citation protocols',()=>{
    expect(safeSource('javascript:alert(1)')).toBeUndefined();
    expect(safeSource('data:text/html,hello')).toBeUndefined();
    expect(safeSource('https://www.ato.gov.au/')).toBe('https://www.ato.gov.au/');
  });
  it('checks file size and format before sending',()=>{
    expect(fileError(new File(['code,name\nA,Example'],'sample.csv'))).toBeUndefined();
    expect(fileError(new File([],'sample.csv'))).toContain('empty');
    expect(fileError(new File(['data'],'sample.xlsx'))).toContain('.csv');
  });
});
