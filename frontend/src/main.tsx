import { useEffect, useId, useState, type FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { api, errorText, type Catalogs, type Config, type Metrics, type Option, type Report, type Stream } from './api'
import './style.css'

const pageSize = 25
const number = new Intl.NumberFormat('ru-RU')
const percent = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const formatCr = (value: number | null) => value === null ? '—' : percent.format(value) + '%'

function Select({ label, options, value, onChange, required = true }: {
  label: string; options: Option[]; value: string; onChange: (value: string) => void; required?: boolean
}) {
  const labelId = useId()
  return (
    <label><span id={labelId}>{label}</span>
      <select aria-labelledby={labelId} required={required} disabled={!required && options.length === 0} value={value} onChange={event => onChange(event.target.value)}>
        <option value="">{required ? 'Выберите' : 'Не задано'}</option>
        {options.map(item => <option key={item.id} value={item.id}>{item.name} · #{item.id}</option>)}
      </select>
    </label>
  )
}

function CampaignForm({ catalogs, config, onCreated }: {
  catalogs: Catalogs; config: Config; onCreated: (campaign: Option, streamId: number) => void
}) {
  const demo = config.mode === 'demo'
  const missing = ([
    ['domains', 'домен', demo], ['groups', 'группа', true],
    ['sources', 'источник', demo], ['offers', 'оффер', true],
  ] as const).filter(([key, , required]) => required && catalogs[key].length === 0).map(([, label]) => label)
  const [name, setName] = useState('')
  const [country, setCountry] = useState('')
  const [offer, setOffer] = useState('')
  const [domain, setDomain] = useState(String(catalogs.domains[0]?.id ?? ''))
  const [group, setGroup] = useState(String(catalogs.groups[0]?.id ?? ''))
  const [source, setSource] = useState(String(catalogs.sources[0]?.id ?? ''))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function create(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await api<Option & { stream_id: number }>('/campaigns', {
        method: 'POST',
        body: JSON.stringify({
          name, country, offer_id: Number(offer), group_id: Number(group),
          domain_id: domain ? Number(domain) : undefined,
          source_id: source ? Number(source) : undefined,
        }),
      })
      onCreated(result, result.stream_id)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="panel-head"><h2>Создание кампании</h2></div>
      <form onSubmit={create}>
        <div className="form-grid">
          <label>Название
            <input required minLength={2} maxLength={65} placeholder="campaign1" value={name}
              onChange={event => setName(event.target.value)} />
            <small>Префикс {config.prefix} добавится автоматически.</small>
          </label>
          <label>Код страны
            <input required pattern="[A-Za-z]{2}" maxLength={2} placeholder="DE" value={country}
              onChange={event => setCountry(event.target.value.toUpperCase())} />
          </label>
          <Select label="Домен" options={catalogs.domains} value={domain} onChange={setDomain} required={demo} />
          <Select label="Группа" options={catalogs.groups} value={group} onChange={setGroup} />
          <Select label="Источник" options={catalogs.sources} value={source} onChange={setSource} required={demo} />
          <Select label="Оффер" options={catalogs.offers} value={offer} onChange={setOffer} />
        </div>
        {!demo && (!domain || !source) && <p className="notice" role="status">
          Кампания будет создана выключенной. Домен и источник можно назначить позже в Keitaro.
        </p>}
        {missing.length > 0 && <p className="notice" role="status">
          В Keitaro нужно настроить следующие справочники: {missing.join(', ')}.
        </p>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="form-actions"><button className="primary" disabled={busy || missing.length > 0}>
          {busy ? 'Создаём…' : 'Создать кампанию'}
        </button></div>
      </form>
    </section>
  )
}

function MetricCells({ metrics }: { metrics?: Metrics }) {
  return <><td>{metrics ? number.format(metrics.clicks) : '—'}</td>
    <td>{metrics ? number.format(metrics.conversions) : '—'}</td>
    <td>{metrics ? formatCr(metrics.cr) : '—'}</td></>
}

function CampaignEditor({ campaign, catalogs, config, preferredStream }: {
  campaign: Option; catalogs: Catalogs; config: Config; preferredStream?: number
}) {
  const [streams, setStreams] = useState<Stream[]>([])
  const [streamId, setStreamId] = useState('')
  const [start, setStart] = useState(config.today)
  const [end, setEnd] = useState(config.today)
  const [report, setReport] = useState<Report | null>(null)
  const [offer, setOffer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reportError, setReportError] = useState('')
  const [loadingStreams, setLoadingStreams] = useState(true)
  const [revision, setRevision] = useState(0)
  const path = '/campaigns/' + campaign.id
  const stream = streams.find(item => String(item.id) === streamId)

  useEffect(() => {
    const controller = new AbortController()
    api<Stream[]>(path + '/streams', { signal: controller.signal }).then(items => {
      setStreams(items)
      const eligible = items.filter(item => item.editable || item.offers.length > 0)
      const preferred = eligible.find(item => item.id === preferredStream)
      setStreamId(String(preferred?.id ?? (eligible.length === 1 ? eligible[0].id : '')))
    }).catch(err => {
      if (!controller.signal.aborted) setError(errorText(err))
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingStreams(false)
    })
    return () => controller.abort()
  }, [path, preferredStream])

  useEffect(() => {
    setReport(null)
    setReportError('')
    if (!streamId || !start || !end) return
    if (start > end) {
      setReportError('Дата окончания должна быть не раньше начала.')
      return
    }
    const controller = new AbortController()
    const query = new URLSearchParams({ start, end })
    api<Report>(path + '/streams/' + streamId + '/stats?' + query, { signal: controller.signal })
      .then(setReport)
      .catch(err => {
        if (!controller.signal.aborted) setReportError(errorText(err))
      })
    return () => controller.abort()
  }, [path, streamId, start, end, revision])

  async function change(offerId: number, remove = false) {
    setBusy(true)
    setError('')
    try {
      const url = path + '/streams/' + streamId + '/offers'
      const result = await api<Stream[]>(remove ? url + '/' + offerId : url, remove
        ? { method: 'DELETE' }
        : { method: 'POST', body: JSON.stringify({ offer_id: offerId }) })
      setStreams(result)
      setOffer('')
      setRevision(value => value + 1)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const activeLinks = stream?.offers ?? []
  const available = catalogs.offers.filter(item => !activeLinks.some(link => link.offer_id === item.id))
  const historic = report?.rows.filter(row => !activeLinks.some(link => link.offer_id === row.offer_id)) ?? []
  const nameOf = (id: number) => catalogs.offers.find(item => item.id === id)?.name ?? 'Оффер #' + id

  return (
    <section className="panel">
      <div className="panel-head"><div><h2>{campaign.name}</h2><p>Кампания #{campaign.id}</p></div></div>
      {loadingStreams && <p className="notice" role="status">Загружаем потоки…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {!loadingStreams && streams.length === 0 && !error && <p className="notice">У кампании пока нет потоков.</p>}
      {streams.length > 0 && <>
        <div className="stream-list" aria-label="Потоки кампании">
          {streams.map(item => <button key={item.id} disabled={busy} aria-pressed={streamId === String(item.id)}
            onClick={() => { setStreamId(String(item.id)); setOffer(''); setError('') }}>
            {item.name} <span>#{item.id}</span>
          </button>)}
        </div>
        {!stream && <p className="notice">Выберите поток для просмотра офферов и статистики.</p>}
      </>}
      {stream && <>
        <div className="filters">
          <label>С<input type="date" value={start} onChange={event => { setReport(null); setStart(event.target.value) }} /></label>
          <label>По<input type="date" value={end} onChange={event => { setReport(null); setEnd(event.target.value) }} /></label>
          <small>{config.timezone}</small>
        </div>
        {reportError && <p className="error" role="alert">{reportError}</p>}
        <div className="table-wrap">
          <table>
            <thead><tr><th>Оффер</th><th>Вес</th><th>Клики</th><th>Конверсии</th><th>CR</th>{stream.editable && <th aria-label="Действие" />}</tr></thead>
            <tbody>
              {activeLinks.map(link => <tr key={link.offer_id}>
                <th scope="row">{nameOf(link.offer_id)}<small>#{link.offer_id}{link.state === 'disabled' ? ' · отключён' : ''}</small></th>
                <td>{link.share}</td>
                <MetricCells metrics={report?.rows.find(row => row.offer_id === link.offer_id)} />
                {stream.editable && <td><button className="remove" disabled={busy || activeLinks.length === 1}
                  title={activeLinks.length === 1 ? 'Последний оффер нельзя удалить' : undefined}
                  aria-label={'Удалить ' + nameOf(link.offer_id)}
                  onClick={() => void change(link.offer_id, true)}>Удалить</button></td>}
              </tr>)}
              {historic.map(row => <tr key={row.offer_id}>
                <th scope="row">{nameOf(row.offer_id)}<small>#{row.offer_id} · история</small></th>
                <td>—</td><MetricCells metrics={row} />{stream.editable && <td />}
              </tr>)}
              {activeLinks.length === 0 && historic.length === 0 && <tr><td colSpan={stream.editable ? 6 : 5}>Нет офферов за выбранный период.</td></tr>}
            </tbody>
            {report && <tfoot><tr><th>Итого</th><td /><MetricCells metrics={report.total} />{stream.editable && <td />}</tr></tfoot>}
          </table>
        </div>
        {stream.editable && <form className="add-form" onSubmit={event => { event.preventDefault(); void change(Number(offer)) }}>
          <Select label="Добавить оффер" options={available} value={offer} onChange={setOffer} />
          <button className="primary" disabled={busy || !offer}>Добавить</button>
        </form>}
      </>}
    </section>
  )
}

function App() {
  const [config, setConfig] = useState<Config>()
  const [catalogs, setCatalogs] = useState<Catalogs>()
  const [campaigns, setCampaigns] = useState<Option[]>([])
  const [selected, setSelected] = useState<Option>()
  const [preferredStream, setPreferredStream] = useState<number>()
  const [screen, setScreen] = useState<'edit' | 'create'>('edit')
  const [offset, setOffset] = useState(0)
  const [listRevision, setListRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [error, setError] = useState('')
  const [listBusy, setListBusy] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    const init = { signal: controller.signal }
    Promise.all([
      api<Config>('/config', init),
      ...(['domains', 'groups', 'sources', 'offers'] as const).map(name => api<Option[]>('/catalogs/' + name, init)),
    ] as const).then(([settings, domains, groups, sources, offers]) => {
      setConfig(settings)
      setCatalogs({ domains, groups, sources, offers })
    }).catch(err => { if (!controller.signal.aborted) setError(errorText(err)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setListBusy(true)
    setListError('')
    api<Option[]>('/campaigns?offset=' + offset + '&limit=' + pageSize, { signal: controller.signal })
      .then(setCampaigns)
      .catch(err => { if (!controller.signal.aborted) setListError(errorText(err)) })
      .finally(() => { if (!controller.signal.aborted) setListBusy(false) })
    return () => controller.abort()
  }, [offset, listRevision])

  function choose(campaign: Option, streamId?: number) {
    setSelected(campaign)
    setPreferredStream(streamId)
    setScreen('edit')
  }

  return <>
    <header className="top">
      <div className="shell top-inner"><strong>AdrobotTask</strong>
        {config && <span className="mode">{config.mode === 'demo' ? 'Локальное демо' : config.mode === 'readonly' ? 'Keitaro · чтение' : 'Keitaro'}</span>}
      </div>
    </header>
    <main className="shell">
      <div className="title"><h1>Кампании</h1>
        {config && config.mode !== 'readonly' && <button className="primary" onClick={() => setScreen(screen === 'create' ? 'edit' : 'create')}>
          {screen === 'create' ? 'К списку' : 'Новая кампания'}
        </button>}
      </div>
      {loading && <p role="status">Загружаем справочники…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {catalogs && config && <div className="workspace">
        <aside className="panel">
          <div className="panel-head"><h2>Список</h2>
            <button className="quiet" disabled={listBusy} onClick={() => setListRevision(value => value + 1)}>Обновить</button>
          </div>
          {listError && <p className="error" role="alert">{listError}</p>}
          {listBusy ? <p className="notice" role="status">Загружаем…</p> : <>
            {campaigns.length === 0 && !listError && <p className="notice">Кампаний на этой странице нет.</p>}
            <div className="campaign-list">
              {campaigns.map(item => <button key={item.id} aria-pressed={screen === 'edit' && selected?.id === item.id}
                onClick={() => choose(item)}><strong>{item.name}</strong><small>#{item.id}</small></button>)}
            </div>
            {(offset > 0 || campaigns.length === pageSize) && <div className="pager">
              <button disabled={offset === 0} onClick={() => setOffset(value => value - pageSize)}>Назад</button>
              <button disabled={campaigns.length < pageSize} onClick={() => setOffset(value => value + pageSize)}>Далее</button>
            </div>}
          </>}
        </aside>
        {screen === 'create' ? <CampaignForm catalogs={catalogs} config={config}
          onCreated={(campaign, streamId) => { choose(campaign, streamId); setListRevision(value => value + 1) }} />
          : selected ? <CampaignEditor key={selected.id} campaign={selected} catalogs={catalogs}
            config={config} preferredStream={preferredStream} />
            : <section className="panel empty"><h2>Выберите кампанию</h2>
              <p>Здесь появятся потоки, офферы и статистика.</p></section>}
      </div>}
    </main>
  </>
}

createRoot(document.getElementById('root')!).render(<App />)
