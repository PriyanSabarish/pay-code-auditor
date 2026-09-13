import { Alert, Button } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Download, FileSpreadsheet } from 'lucide-react';
import { api } from '../api/client';
import type { SampleBusiness } from '../api/client';

/** Lets a reviewer inspect or load one of the bundled example businesses without
 * needing to source their own payroll exports first. */
export default function SampleData({ onUseSample }: { onUseSample: (business: SampleBusiness) => void }) {
  const samples = useQuery({ queryKey: ['samples'], queryFn: ({ signal }) => api.samples(signal), staleTime: 60_000 });

  return <main className="sample-page" aria-labelledby="sample-page-title">
    <div className="section-heading">
      <div><div className="eyebrow">SAMPLE DATA</div><h1 id="sample-page-title">Try it with example payroll data.</h1></div>
    </div>
    <p className="sample-page-intro">
      Each sample is a small, realistic payroll export with a handful of pay codes deliberately set up incorrectly —
      useful for seeing how a review reads before bringing your own files. Download the CSVs to look them over, or
      load one straight into the workspace with one click.
    </p>
    {samples.error && <Alert color="red" title="Couldn't load the sample list">{samples.error.message}</Alert>}
    {samples.isPending && <p className="sample-page-loading">Loading samples…</p>}
    <div className="sample-grid">
      {samples.data?.map(business => <article key={business.id} className="sample-card">
        <div className="sample-card-heading"><FileSpreadsheet size={20} /><h2>{business.name}</h2></div>
        <p>{business.description}</p>
        <span className="sample-card-count">{business.paycode_count} pay codes</span>
        <div className="sample-card-actions">
          <a className="sample-download" href={api.samplePaycodesUrl(business.id)} download={`${business.id}-paycodes.csv`}>
            <Download size={14} /> Pay codes.csv
          </a>
          <a className="sample-download" href={api.samplePayrunsUrl(business.id)} download={`${business.id}-payruns.csv`}>
            <Download size={14} /> Pay runs.csv
          </a>
        </div>
        <Button fullWidth mt="sm" rightSection={<ArrowRight size={15} />} onClick={() => onUseSample(business)}>
          Use this sample
        </Button>
      </article>)}
    </div>
  </main>;
}
