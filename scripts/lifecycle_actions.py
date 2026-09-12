"""可重新载入的诊断动作；在同一专用浏览器中完成后续核查。"""

import json
import re
from urllib.parse import parse_qs, urlsplit
from urllib.parse import urljoin

from scripts.qualification_trace import DOM_OBSERVER
from src.card_save import CARD_IDENTITY_JS
from src.errors import PageFlowError
from src.new_audit_qualification import evidence_urls_match
from src.upload_identity import UploadReceipt, preview_files, verify_preview_content, verify_saved_request
from src.workflow import select_url_and_open_industry_qualification


def execute(runner, command):
    if command == 'verify-native-refresh':
        before = [[(f['id'], f['url']) for f in preview_files(runner.view._upload_container(i))]
                  for i in runner.view._file_inputs_in(runner.page)]
        import importlib
        from src import new_audit_qualification
        method = importlib.reload(new_audit_qualification).NewAuditQualificationPage._refresh_business_from_page
        ok = method(runner.view, runner.page)
        runner.page.wait_for_timeout(1500)
        after = [[(f['id'], f['url']) for f in preview_files(runner.view._upload_container(i))]
                 for i in runner.view._file_inputs_in(runner.page)]
        print('NATIVE_REFRESH', {'completed':ok,'preserved':before==after,'counts':[len(x) for x in after]},flush=True)
    elif command == 'add-page-source':
        responses = [(q, r) for q, r in runner.trace.responses.items()
                     if q.resource_type == 'script' and urlsplit(q.url).hostname == 'defstatic.bj.bcebos.com']
        for request, response in responses:
            try: source = response.text()
            except Exception: continue
            found = re.search(r'assets/(AddInvestLice-[A-Za-z0-9_-]+\.js)', source)
            if not found: continue
            url = urljoin(request.url, found.group(1))
            result = runner.page.request.get(url)
            if result.status != 200: continue
            (runner.trace.directory/'static-sources'/'add-page.js').write_text(result.text(),encoding='utf-8')
            reserve = re.search(r'\./(AddReserveLice-[A-Za-z0-9_-]+\.js)', result.text())
            if reserve:
                other = runner.page.request.get(urljoin(url, reserve.group(1)))
                if other.status == 200:
                    (runner.trace.directory/'static-sources'/'reserve.js').write_text(other.text(),encoding='utf-8')
            print('ADD_PAGE_SOURCE_SAVED', flush=True)
            break
    elif command == 'static-sources':
        output = runner.trace.directory / 'static-sources'
        output.mkdir(exist_ok=True)
        count = 0
        for request, response in list(runner.trace.responses.items()):
            if request.resource_type != 'script' or urlsplit(request.url).hostname != 'defstatic.bj.bcebos.com':
                continue
            try: source = response.text()
            except Exception: continue
            if not any(word in source for word in ('geturlinfo', 'BusinessFormCard', 'submitlice', 'geturlandproductinfo')):
                continue
            count += 1
            (output / f'bundle-{count}.js').write_text(source, encoding='utf-8')
        print('STATIC_SOURCE_COUNT', count, flush=True)
    elif command == 'detail-shape':
        summaries = []
        for request, response in list(runner.trace.responses.items()):
            endpoint = urlsplit(request.url).path.rsplit('/', 1)[-1]
            if endpoint not in ('geturlinfo', 'geturlandproductinfo'):
                continue
            try:
                body = response.json()
            except Exception:
                continue
            data = body.get('data', {}) if isinstance(body, dict) else {}
            groups = data.get('trade_lice_info', {}).get('opt', []) if isinstance(data, dict) else []
            summary = {'endpoint': endpoint, 'status': body.get('status'), 'groups': [
                {'identity': runner.trace.redactor.data({k:v for k,v in group.items() if k != 'data'}),
                 'records': [{'identity': runner.trace.redactor.data({k:v for k,v in record.items() if k not in ('filename','evidence_url')}),
                              'file_count': len([x for x in str(record.get('filename','')).split(',') if x]),
                              'evidence_present': bool(record.get('evidence_url'))} for record in group.get('data', [])]}
                for group in groups]}
            summaries.append(summary)
        (runner.trace.directory/'detail-shape.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
        print('DETAIL_SHAPES', [(s['endpoint'],s['status'],[len(g['records']) for g in s['groups']]) for s in summaries], flush=True)
    elif command == 'audit-read-errors':
        for request,response in list(runner.trace.responses.items()):
            if urlsplit(request.url).path not in ('/permit/web/permit/geturlinfo','/permit/web/permit/geturlandproductinfo'):
                continue
            try: body=response.json()
            except Exception: continue
            if not isinstance(body,dict) or body.get('status') in (0,None):continue
            message=str(body.get('message',''))
            print('READ_ERROR',body.get('status'),{'chinese':re.findall(r'[\u4e00-\u9fff]{2,}',message),
                'english':re.findall(r'\b(?:error|invalid|expired|missing|argument|arguments|token|permission|denied|timeout|retry|failed|busy|system|server|request|parameter|params|curl|exec|rpc|sql|redis|db|database|service|connect|connection|socket|network|check|verify|signature|sign|decrypt|encrypt|auth|authentication|access|upstream)\b',message,re.I)},flush=True)
    elif command == 'audit-parent-refresh':
        result = runner.card().evaluate('''element=>{
          const found=[],seen=new Set();
          const consider=c=>{
            const root=c?.subTree?.el;
            if(root===element || (root?.classList?.contains('drag-upload-wrapper') && root.querySelector('.form-card')===element)){
              for(let owner=c;owner;owner=owner.parent){
                const props=owner.vnode?.props||{},handlers={};
                for(const key of Object.keys(props).filter(k=>/getlist|trigger.update|refresh|^onInit$/i.test(k))){
                  const fns=Array.isArray(props[key])?props[key]:[props[key]];
                  handlers[key]=fns.filter(f=>typeof f==='function').map(f=>f.toString());
                }
                found.push({name:owner.type?.__name||owner.type?.name||'',keys:Object.keys(owner.exposed||{}),handlers});
              }
            }
          };
          let root=element;while(root&&!root._vnode)root=root.parentElement;
          const walk=v=>{if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
            if(v.component){consider(v.component);walk(v.component.subTree);}
            if(Array.isArray(v.children))v.children.forEach(walk);if(v.suspense)walk(v.suspense.activeBranch);};
          walk(root?._vnode);return found;
        }''')
        (runner.trace.directory/'parent-refresh.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('REFRESH_HANDLER_AUDIT',len(result),flush=True)
    elif command == 'prepare-next':
        source = next(t for t in runner.company.qualification_types if t.type_name == '推广审查')
        inputs = runner.view._file_inputs_in(runner.page)
        if len(inputs) != 1 or len(source.qualifications) < 2:
            raise PageFlowError('next-card-precondition-not-met')
        first = runner.view._upload_container(inputs[0])
        files = preview_files(first)
        if len(files) != len(source.qualifications[0].files):
            raise PageFlowError('existing-first-card-file-count-mismatch')
        import hashlib
        runner.preserved_receipts = [UploadReceipt(path.resolve(), hashlib.sha256(path.read_bytes()).hexdigest(), item['id'])
            for path, item in zip(source.qualifications[0].files, files)]
        runner.view._verify_file_receipts(lambda: runner.view._upload_container(runner.view._file_inputs_in(runner.page)[0]),
                                         runner.preserved_receipts, 'preserved-first', content=True)
        runner.target_type = source
        runner.qualification = source.qualifications[1]
        runner.target_card_index = 1
        runner.trace.mark('prepare_next_empty_qualification')
        runner.view._ensure_upload_form_count_in(lambda: runner.page, 2)
        runner.card = lambda: runner.view._upload_container(runner.view._file_inputs_in(runner.page)[runner.target_card_index])
        if preview_files(runner.card()):
            raise PageFlowError('next-card-not-empty')
        print('NEXT_CARD_PREPARED', flush=True)
        runner.inspect()
    elif command == 'upload-next':
        if getattr(runner, 'target_card_index', None) != 1 or preview_files(runner.card()):
            raise PageFlowError('next-card-not-prepared-or-not-empty')
        runner.allow_writes = True
        runner.trace.mark('before_first_file')
        runner.view._upload_qualification_in(runner.target_type, 0, 1, lambda: runner.page)
        runner.upload_completed = True
        runner.trace.mark('qualification_upload_completed')
        runner.page.wait_for_timeout(1500)
        runner.inspect()
        print('UPLOAD_COMPLETED', flush=True)
    elif command == 'verify-next':
        if not runner.upload_completed:
            raise PageFlowError('no-completed-upload-to-verify')
        receipts = runner.view._saved_file_receipts.get((0, 1), ())
        if len(receipts) != len(runner.qualification.files):
            raise PageFlowError('missing-upload-receipts')
        runner.allow_writes = False
        runner.trace.mark('reopen_saved_detail')
        runner.page.reload(wait_until='domcontentloaded', timeout=runner.config.page_timeout_ms)
        runner.view._wait_until(lambda: len(runner.view._file_inputs_in(runner.page)) == 2, 'reopened-card-count-mismatch')
        runner.view._verify_file_receipts(runner.card, receipts, 'reopened-next', content=True)
        first = lambda: runner.view._upload_container(runner.view._file_inputs_in(runner.page)[0])
        runner.view._verify_file_receipts(first, runner.preserved_receipts, 'preserved-first', content=True)
        preserved_evidence = runner.view._unique_visible(first().locator('input:not([type=file])'), '已有资质举证链接')
        if not evidence_urls_match(preserved_evidence.input_value(), runner.target_type.qualifications[0].evidence_url or ''):
            raise PageFlowError('preserved-first-evidence-mismatch')
        field = runner.view._unique_visible(runner.card().locator('input:not([type=file])'), '举证链接')
        if not evidence_urls_match(field.input_value(), runner.qualification.evidence_url or ''):
            raise PageFlowError('persisted-evidence-mismatch')
        runner.trace.mark('persisted_qualification_verified')
        result = {'production_flow_returned_success': True, 'ui_edit_verified': True, 'file_count': len(receipts),
                  'preserved_first_card': True, 'evidence_matches': True,
                  'files': [{'file_ref': runner.trace.redactor.alias(r.server_id), 'sha256': r.sha256} for r in receipts]}
        runner.trace.emit('verification', **result)
        (runner.trace.directory/'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PERSISTENCE_VERIFIED', len(receipts), flush=True)
    elif command == 'verify-readback-api':
        import importlib
        from src import card_save
        observer_type = importlib.reload(card_save).CardSaveObserver
        receipts = runner.view._saved_file_receipts.get((0, 1), ())
        if not receipts:
            raise PageFlowError('no-completed-receipts')
        with observer_type(runner.page) as observer:
            # Seed with the requests already observed in this browser session.
            for request, response in list(runner.trace.responses.items()):
                observer._request(request)
                observer._response(response)
                observer._finished(request)
            identity = runner.card().evaluate(CARD_IDENTITY_JS)
            matched = observer.readback(0, identity, receipts, runner.qualification.evidence_url or '', runner.config.page_timeout_ms)
        runner.trace.emit('readback_api_verification', matched=matched)
        print('READBACK_API_MATCH', matched, flush=True)
    elif command == 'card-identity':
        print('CARD_IDENTITY', runner.trace.redactor.data(runner.card().evaluate(CARD_IDENTITY_JS)), flush=True)
    elif command == 'page-state':
        for page in runner.session.context.pages:
            if page.is_closed():
                continue
            labels = ['URL状态概览', '投放资质', '已备案业务资质', '新增资质',
                      '新增业务资质', '推广审查', '已保存待送审', '待审核', '共 0 个业务资质']
            result = {'page': runner.trace.page_id(page), 'url': runner.trace.redactor.url(page.url),
                      'markers': {s: len([x for x in page.get_by_text(s, exact=True).all() if x.is_visible()]) for s in labels},
                      'file_inputs': page.locator('input[type=file]').count()}
            runner.trace.emit('page_state', **result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    elif command == 'resume-navigation':
        pages = [p for p in runner.session.context.pages if not p.is_closed()
                 and p.get_by_text('URL状态概览', exact=True).count()]
        if len(pages) != 1:
            raise PageFlowError('overview-not-unique')
        runner.trace.mark('resume_read_only_navigation')
        page = select_url_and_open_industry_qualification(pages[0], runner.company.url, runner.config.page_timeout_ms)
        runner._run_industry_qualification(page, runner.company)
    elif command == 'open-new':
        if runner.page is None or runner.page.locator('input[type=file]').count():
            raise PageFlowError('not-at-detail-list')
        runner.trace.mark('open_new_business_form')
        runner.view.enter_add_business_page(allow_resume=False)
        indices = runner.view._business_indices_matching('推广审查')
        if len(indices) != 1:
            raise PageFlowError('promotion-business-not-unique')
        runner.view._click_business_tab(indices[0])
        runner.target_business_index = indices[0]
        runner.inspect()
    elif command == 'prepare-capture':
        for page in runner.session.context.pages:
            if page.is_closed():
                continue
            page.evaluate(DOM_OBSERVER)
            print('OBSERVER', runner.trace.page_id(page), page.evaluate(
                '({installed:!!window.__bpfTraceInstalled,binding:typeof window.__bpfTrace})'), flush=True)
        if not hasattr(runner, 'target_business_index') and runner.view._business_tabs():
            matches = runner.view._business_indices_matching('推广审查')
            if len(matches) != 1:
                raise PageFlowError('promotion-business-not-unique')
            runner.target_business_index = matches[0]
            runner.view._click_business_tab(matches[0])
        if hasattr(runner, 'target_business_index'):
            def target_card():
                scope = runner.view._business_container(runner.target_business_index)
                if scope is None or not runner.view._business_type_matches(scope, '推广审查'):
                    raise PageFlowError('target-business-mismatch')
                inputs = runner.view._file_inputs_in(scope)
                if not inputs:
                    raise PageFlowError('target-card-missing')
                return runner.view._upload_container(inputs[0])
            runner.card = target_card
        runner.trace.mark('capture_prepared_before_first_file')
        print('TARGET_FILES', len(runner.card().locator('.preview-list-li').all()), flush=True)
    elif command == 'verify-persisted-observed':
        # Recover receipts for read-only investigation, not for another upload/save attempt.
        uploads = [response for request, response in runner.trace.responses.items()
                   if urlsplit(request.url).path == '/permit/web/permit/savelicepic'
                   and request.method == 'POST']
        if len(uploads) != len(runner.qualification.files):
            raise PageFlowError('observed-upload-count-not-exact')
        receipts = [UploadReceipt.from_response(path, response)
                    for path, response in zip(runner.qualification.files, uploads)]
        saves = [response for request, response in runner.trace.responses.items()
                 if urlsplit(request.url).path == '/permit/web/permit/submitlice'
                 and request.method == 'POST' and response.status == 200
                 and response.json().get('status') == 0]
        if not saves:
            raise PageFlowError('no-successful-save-observed')
        verify_saved_request(saves[-1], receipts, runner.qualification.evidence_url or '')
        runner.allow_writes = False
        runner.trace.mark('verify_after_production_flow_error')
        verify_preview_content(runner.page, receipts, preview_files(runner.card()), runner.config.page_timeout_ms)
        runner.trace.mark('reopen_persisted_business_list')
        runner.page.goto(runner.detail_url, wait_until='domcontentloaded', timeout=runner.config.page_timeout_ms)
        if not runner.view._open_saved_promotion_for_edit():
            raise PageFlowError('saved-promotion-not-found-after-reopen')
        runner.card = lambda: runner.view._upload_container(runner.view._file_inputs_in(runner.page)[0])
        runner.trace.mark('verify_reopened_persisted_files')
        runner.view._verify_file_receipts(runner.card, receipts, 'target', content=True)
        field = runner.view._unique_visible(runner.card().locator('input:not([type=file])'), '举证链接')
        if not evidence_urls_match(field.input_value(), runner.qualification.evidence_url or ''):
            raise PageFlowError('persisted-evidence-mismatch')
        runner.trace.mark('persisted_qualification_verified')
        result = {'file_count': len(receipts), 'files': [{'file_ref': runner.trace.redactor.alias(r.server_id),
                  'sha256': r.sha256} for r in receipts], 'evidence_matches': True,
                  'production_flow_returned_success': runner.upload_completed}
        runner.trace.emit('verification', **result)
        (runner.trace.directory/'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PERSISTENCE_VERIFIED', len(receipts), flush=True)
    elif command == 'audit-page-methods':
        runner.trace.mark('read_only_component_audit')
        result = runner.card().evaluate('''element => {
          const found=[],seen=new Set();
          const consider=c=>{
            const root=c?.subTree?.el;
            if ((root===element || (root?.classList?.contains('drag-upload-wrapper') && root.querySelector('.form-card')===element)) && c.exposed) {
              const api=c.exposed, methods={};
              for(const key of ['handleSubmit','isValid','formatFormData'])
                if(typeof api[key]==='function') methods[key]=api[key].toString();
              found.push({keys:Object.keys(api),methods});
            }
          };
          let root=element;while(root&&!root._vnode)root=root.parentElement;
          const walk=v=>{if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
            if(v.component){consider(v.component);walk(v.component.subTree);}
            if(Array.isArray(v.children))v.children.forEach(walk);
            if(v.suspense)walk(v.suspense.activeBranch);};
          walk(root?._vnode);return found;
        }''')
        # Public function source contains variable references, not closure/session values.
        (runner.trace.directory/'page-methods.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('EXPOSED_METHODS', [item['keys'] for item in result], flush=True)
    elif command == 'network-status':
        for request, response in runner.trace.responses.items():
            path = urlsplit(request.url).path
            if not path.startswith('/permit/') or 'json' not in response.headers.get('content-type', ''):
                continue
            try:
                body = response.json()
            except Exception:
                continue
            if isinstance(body, dict) and body.get('status') not in (0, None):
                message = str(body.get('message') or '')
                # Only entirely Chinese error phrases are displayed, never echoed URLs or identifiers.
                safe_message = message if re.fullmatch(r'[\u4e00-\u9fff，。：；！？（）\s]{1,100}', message) else '[redacted]'
                print('API_ERROR', path, body.get('status'), safe_message, flush=True)
    elif command == 'audit-card-events':
        runner.trace.mark('read_only_card_event_audit')
        result = runner.card().evaluate('''element => {
          const result=[];
          for(let node=element;node && result.length<12;node=node.parentElement){
            const maps=[node._vei,...Object.getOwnPropertySymbols(node).filter(s=>String(s).includes('_vei')).map(s=>node[s])];
            for(const map of maps){if(!map)continue;
              for(const [event,invoker] of Object.entries(map)){
                const fn=invoker?.value || invoker;
                if(/leave|blur|change/i.test(event)) result.push({event,source:typeof fn==='function'?fn.toString():null});
              }
            }
          }
          return result;
        }''')
        (runner.trace.directory/'card-events.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('CARD_EVENTS', [x['event'] for x in result], flush=True)
    elif command == 'reload-current-readonly':
        runner.allow_writes = False
        runner.trace.mark('reload_current_edit_readonly')
        runner.page.reload(wait_until='domcontentloaded', timeout=runner.config.page_timeout_ms)
    elif command == 'verify-server-record':
        uploads = [response for request, response in runner.trace.responses.items()
                   if urlsplit(request.url).path == '/permit/web/permit/savelicepic']
        if len(uploads) != len(runner.qualification.files):
            raise PageFlowError('observed-upload-count-not-exact')
        receipts = [UploadReceipt.from_response(path, response)
                    for path, response in zip(runner.qualification.files, uploads)]
        expected_ids = [r.server_id for r in receipts]
        details = [response for request, response in runner.trace.responses.items()
                   if urlsplit(request.url).path == '/permit/web/permit/geturlandproductinfo'
                   and response.status == 200 and response.json().get('status') == 0]
        if not details:
            raise PageFlowError('no-successful-detail-response')
        rows = details[-1].json()['data']['trade_lice_info']['opt']
        matches = [item for group in rows for item in group.get('data', [])
                   if item.get('filename', '').split(',') == expected_ids]
        if len(matches) != 1 or not evidence_urls_match(matches[0].get('evidence_url', ''), runner.qualification.evidence_url or ''):
            raise PageFlowError('fresh-detail-file-or-evidence-mismatch')
        files = []
        for identifier in expected_ids:
            urls = [request.url for request in runner.trace.requests
                    if urlsplit(request.url).path == '/permit/web/permit/getlicepic'
                    and parse_qs(urlsplit(request.url).query).get('filename') == [identifier]]
            if not urls:
                raise PageFlowError('no-observed-preview-url')
            files.append({'id': identifier, 'url': urls[-1], 'ready': True})
        runner.trace.mark('verify_persisted_server_record_content')
        verify_preview_content(runner.page, receipts, files, runner.config.page_timeout_ms)
        result = {'file_count': len(receipts), 'files': [{'file_ref': runner.trace.redactor.alias(r.server_id),
                  'sha256': r.sha256} for r in receipts], 'evidence_matches': True,
                  'method': 'fresh-detail-response-and-observed-preview-urls',
                  'production_flow_returned_success': runner.upload_completed,
                  'detail_request_id': runner.trace.requests[details[-1].request][0]}
        if (urlsplit(runner.page.url).fragment.startswith('/lice/edit_invest_lice/')
                and len(runner.view._file_inputs_in(runner.page)) == 1):
            runner.card = lambda: runner.view._upload_container(runner.view._file_inputs_in(runner.page)[0])
            runner.view._verify_file_receipts(runner.card, receipts, 'reopened-target')
            field = runner.view._unique_visible(runner.card().locator('input:not([type=file])'), '举证链接')
            if not evidence_urls_match(field.input_value(), runner.qualification.evidence_url or ''):
                raise PageFlowError('reopened-ui-evidence-mismatch')
            result['ui_edit_verified'] = True
        runner.trace.mark('persisted_qualification_verified')
        runner.trace.emit('verification', **result)
        (runner.trace.directory/'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PERSISTENCE_VERIFIED_FROM_SERVER', len(receipts), flush=True)
    else:
        print('UNKNOWN_COMMAND', flush=True)
