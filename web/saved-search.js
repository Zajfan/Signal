import {api} from './shared.js';

// A saved list can exceed HTTP request-line limits when combined with filters.
// Fetch bounded groups, then apply the same stable ordering and pagination.
export async function searchSavedJobs(params, savedIds) {
  const offsetText = params.get('offset')?.trim() || '0';
  if (!/^\d{1,9}$/.test(offsetText)) throw Error('Pagination must be nonnegative integers');
  const offset = Number(offsetText), limit = 20;
  const base = new URLSearchParams(params);
  base.set('limit', '100'); base.set('offset', '0'); base.delete('ids');
  const urlFor = ids => {
    const query = new URLSearchParams(base);
    query.set('ids', ids.join(','));
    return '/api/v1/jobs?' + query;
  };
  const urls = [];
  let group = [];
  for (const id of [...new Set(savedIds)]) {
    if (group.length && (group.length === 50 || urlFor([...group, id]).length > 7500)) {
      urls.push(urlFor(group)); group = [];
    }
    group.push(id);
    if (urlFor(group).length > 7500) throw Error('This saved-job search is too long. Shorten the search text.');
  }
  if (group.length) urls.push(urlFor(group));
  if (!urls.length) return {jobs: [], total: 0, limit, offset};
  const results = await Promise.all(urls.map(url => api(url)));
  const jobs = results.flatMap(result => result.jobs);
  const seconds = value => Number.isFinite(Date.parse(value)) ? Math.floor(Date.parse(value) / 1000) : -Infinity;
  jobs.sort((a,b) => Number(b.is_featured)-Number(a.is_featured)
    || seconds(b.created_at)-seconds(a.created_at) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return {jobs: jobs.slice(offset, offset+limit), total: jobs.length, limit, offset};
}
