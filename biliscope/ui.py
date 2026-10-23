from __future__ import annotations
from dataclasses import replace
import json
import logging
import math
from pathlib import Path
import queue
import tkinter as tk
from tkinter import messagebox,scrolledtext,ttk
from .config import Settings
from .credentials import load_key,save_key
from .domain import AppError,comment_payload,timestamp
from .i18n import tr
from .runtime import ROOT,RUNTIME,inside,atomic_json,path_report,redact,remember_secret
from .service import Service
from .auto import AutoPlan
from .prompts import PRESETS,CORE,preset_text

log=logging.getLogger('biliscope')

class App:
    def __init__(self):
        self.root=tk.Tk()
        self.root.geometry('1140x860');self.root.minsize(900,700)
        self.queue=queue.Queue();self.future=None;self.closing=False
        self.text_bindings=[];self.field_widgets={};self.mentions=[];self.reply=None
        self.photos=[]
        self.auto_running=False
        self.auto_enabled=tk.BooleanVar(value=False)
        self.display_evidence=None
        try:self.auto_plan=AutoPlan.load()
        except Exception:self.auto_plan=AutoPlan()
        try: self.settings=Settings.load()
        except Exception:
            self.settings=Settings();log.warning('Invalid settings; using defaults')
        self.lang=self.settings.language
        try: key=load_key()
        except Exception:
            key='';log.warning('Saved key could not be decrypted')
        remember_secret(key)
        self.vars={
            'target':tk.StringVar(), 'key':tk.StringVar(value=key),
            'language':tk.StringVar(value=self.lang.upper()),
        }
        for k,v in vars(self.settings).items():
            if k=='language': continue
            self.vars[k]=tk.BooleanVar(value=v) if isinstance(v,bool) else tk.StringVar(value=str(v))
        self.auto_vars={}
        for k,v in vars(self.auto_plan).items():
            self.auto_vars[k]=tk.BooleanVar(value=v) if isinstance(v,bool) else tk.StringVar(value=str(v))
        self.style=ttk.Style(self.root)
        self.style.theme_use('clam')
        self.style.configure('TFrame',background='#f4f7fb')
        self.style.configure('TLabel',background='#f4f7fb',foreground='#1a2940',font=('Segoe UI',10))
        self.style.configure('Title.TLabel',font=('Segoe UI',24,'bold'))
        self.style.configure('TButton',font=('Segoe UI',10),padding=(12,7))
        self.style.configure('Accent.TButton',background='#007d88',foreground='white')
        self.style.configure('TLabelframe',background='#f4f7fb')
        self.style.configure('TLabelframe.Label',background='#f4f7fb',foreground='#1a2940')
        self.style.configure('TCheckbutton',background='#f4f7fb')
        self.style.configure('Treeview',rowheight=28,font=('Segoe UI',10))
        self.style.configure('TNotebook.Tab',padding=(18,9))
        outer=ttk.Frame(self.root,padding=22);outer.pack(fill='both',expand=True)
        header=ttk.Frame(outer);header.pack(fill='x')
        self.label(header,'app_title',style='Title.TLabel').pack(side='left')
        combo=ttk.Combobox(header,textvariable=self.vars['language'],values=['CN','EN'],state='readonly',width=5)
        combo.pack(side='right');combo.bind('<<ComboboxSelected>>',self.change_language)
        self.label(outer,'tagline').pack(anchor='w',pady=(4,15))
        self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
        self.pages={k:ttk.Frame(self.tabs,padding=16) for k in ('video_tab','comment_tab','auto_tab','prompts_tab','settings_tab','diagnostics_tab')}
        for k,page in self.pages.items(): self.tabs.add(page,text=self.t(k))
        self.build_video();self.build_comment();self.build_auto();self.build_prompts();self.build_settings();self.build_diagnostics()
        self.status=tk.StringVar(value=self.t('ready'))
        ttk.Label(outer,textvariable=self.status,wraplength=1050).pack(anchor='w',pady=(12,0))
        self.service=Service(self.queue.put)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.after(100,self.poll)
        self.translate()

    def t(self,key): return tr(key,self.lang)

    def label(self,parent,key,**kw):
        w=ttk.Label(parent,text=self.t(key),**kw);self.text_bindings.append((w,key));return w

    def button(self,parent,key,command,**kw):
        w=ttk.Button(parent,text=self.t(key),command=command,**kw);self.text_bindings.append((w,key));return w

    def check(self,parent,key,var):
        w=ttk.Checkbutton(parent,text=self.t(key),variable=self.vars[var]);self.text_bindings.append((w,key));return w

    def build_video(self):
        p=self.pages['video_tab']
        self.label(p,'target').pack(anchor='w')
        ttk.Entry(p,textvariable=self.vars['target'],font=('Segoe UI',11)).pack(fill='x',pady=(5,10))
        self.label(p,'question').pack(anchor='w')
        self.question=tk.Text(p,height=2,font=('Segoe UI',11),wrap='word',relief='solid',bd=1)
        self.question.pack(fill='x',pady=(5,10));self.question.insert('1.0',self.t('default_question'))
        row=ttk.Frame(p);row.pack(fill='x',pady=(0,8))
        self.button(row,'login',lambda:self.task(self.service.browser.login(),self.login_done)).pack(side='left')
        self.button(row,'analyze',self.analyze,style='Accent.TButton').pack(side='left',padx=8)
        self.button(row,'cancel',self.cancel).pack(side='left')
        self.button(row,'export',self.export).pack(side='right')
        self.label(p,'privacy_hint',wraplength=1000).pack(anchor='w',pady=(0,10))
        self.video_title=tk.StringVar()
        ttk.Label(p,textvariable=self.video_title,font=('Segoe UI',12,'bold'),wraplength=1000).pack(anchor='w')
        panes=ttk.Panedwindow(p,orient='vertical');panes.pack(fill='both',expand=True,pady=(8,0))
        upper=ttk.Frame(panes);lower=ttk.Frame(panes);panes.add(upper,weight=4);panes.add(lower,weight=1)
        self.result=scrolledtext.ScrolledText(upper,wrap='word',font=('Segoe UI',11),height=14,padx=12,pady=10)
        self.result.pack(fill='both',expand=True);self.result.configure(state='disabled')
        self.label(lower,'evidence').pack(anchor='w',pady=(5,4))
        self.frames=ttk.Treeview(lower,columns=('actual','requested','source'),show='headings',height=3)
        self.frames.column('actual',width=130);self.frames.column('requested',width=130)
        self.frames.pack(fill='both',expand=True);self.frames.bind('<Double-1>',self.show_frame)

    def build_comment(self):
        p=self.pages['comment_tab']
        row=ttk.Frame(p);row.pack(fill='x')
        self.button(row,'fetch_comments',self.fetch_comments).pack(side='left')
        self.button(row,'reply_selected',self.select_reply).pack(side='left',padx=8)
        self.button(row,'new_comment',self.clear_reply).pack(side='left')
        self.comment_tree=ttk.Treeview(p,columns=('name','uid','message'),show='headings',height=7)
        self.comment_tree.column('name',width=160);self.comment_tree.column('uid',width=130)
        self.comment_tree.column('message',width=650)
        self.comment_tree.pack(fill='both',expand=True,pady=12)
        self.reply_label=tk.StringVar();ttk.Label(p,textvariable=self.reply_label,wraplength=1000).pack(anchor='w')
        row=ttk.Frame(p);row.pack(fill='x',pady=10)
        self.label(row,'mention_uid').pack(side='left')
        self.uid=tk.StringVar();ttk.Entry(row,textvariable=self.uid,width=18).pack(side='left',padx=8)
        self.button(row,'add_mention',self.add_mention).pack(side='left')
        self.button(row,'clear_mentions',self.clear_mentions).pack(side='left',padx=8)
        self.mention_label=tk.StringVar();ttk.Label(p,textvariable=self.mention_label,wraplength=1000).pack(anchor='w')
        self.label(p,'compose').pack(anchor='w',pady=(10,5))
        self.compose=tk.Text(p,height=7,font=('Segoe UI',11),wrap='word',relief='solid',bd=1)
        self.compose.pack(fill='x')
        row=ttk.Frame(p);row.pack(fill='x',pady=12)
        self.button(row,'draft',self.draft).pack(side='left')
        self.button(row,'publish',self.publish,style='Accent.TButton').pack(side='right')

    def scroll_panel(self,parent):
        canvas=tk.Canvas(parent,background='#f4f7fb',highlightthickness=0)
        bar=ttk.Scrollbar(parent,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        body=ttk.Frame(canvas)
        window=canvas.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        canvas.bind('<MouseWheel>',lambda e:canvas.yview_scroll(int(-e.delta/120),'units'))
        return body

    def build_auto(self):
        p=self.scroll_panel(self.pages['auto_tab']);p.columnconfigure(1,weight=1)
        toggle=ttk.Checkbutton(p,text=self.t('auto_enable'),variable=self.auto_enabled,command=self.toggle_auto)
        self.text_bindings.append((toggle,'auto_enable'));toggle.grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,8))
        self.label(p,'auto_hint',wraplength=970).grid(row=1,column=0,columnspan=2,sticky='w',pady=(0,10))
        row=2
        self.label(p,'source_mode').grid(row=row,column=0,sticky='w',pady=5)
        ttk.Combobox(p,textvariable=self.auto_vars['source_mode'],values=['recommendations','search','queue'],state='readonly',width=23).grid(row=row,column=1,sticky='w');row+=1
        for key in ('keyword','start_time','owner_uid','question','comment_instruction'):
            self.label(p,'auto_'+key).grid(row=row,column=0,sticky='w',pady=5,padx=(0,14))
            ttk.Entry(p,textvariable=self.auto_vars[key],width=58).grid(row=row,column=1,sticky='ew',pady=5);row+=1
        for key,low,high in [('interval_minutes',1,1440),('duration_minutes',1,1440),('max_videos',1,100),
                              ('max_posts',1,100),('daily_post_limit',1,100),('daily_analysis_limit',1,1000),
                              ('owner_every_minutes',1,1440),('owner_daily_limit',1,100),
                              ('quality_threshold',1,10),('max_analyze_failures',1,10),
                              ('analysis_backoff_minutes',1,1440)]:
            self.label(p,'auto_'+key).grid(row=row,column=0,sticky='w',pady=4)
            ttk.Spinbox(p,from_=low,to=high,textvariable=self.auto_vars[key],width=10).grid(row=row,column=1,sticky='w');row+=1
        for key in ('publish_comments','mention_owner','mention_only','run_until_stopped','quality_gate','mention_requires_quality'):
            widget=ttk.Checkbutton(p,text=self.t('auto_'+key),variable=self.auto_vars[key])
            self.text_bindings.append((widget,'auto_'+key));widget.grid(row=row,column=0,columnspan=2,sticky='w',pady=7);row+=1
        self.label(p,'auto_queue_text').grid(row=row,column=0,columnspan=2,sticky='w');row+=1
        self.auto_queue=scrolledtext.ScrolledText(p,height=4,wrap='word',font=('Segoe UI',10))
        self.auto_queue.insert('1.0',self.auto_plan.queue_text)
        self.auto_queue.grid(row=row,column=0,columnspan=2,sticky='ew',pady=6);row+=1
        actions=ttk.Frame(p);actions.grid(row=row,column=0,columnspan=2,sticky='ew',pady=7)
        self.button(actions,'auto_save',self.save_auto).pack(side='left')
        self.button(actions,'cancel',self.cancel).pack(side='left',padx=8);row+=1
        self.auto_results=ttk.Treeview(p,columns=('video','result'),show='headings',height=5)
        self.auto_results.column('video',width=170);self.auto_results.column('result',width=650)
        self.auto_results.grid(row=row,column=0,columnspan=2,sticky='ew',pady=(5,10))

    def build_prompts(self):
        p=self.pages['prompts_tab']
        row=ttk.Frame(p);row.pack(fill='x')
        self.label(row,'prompt_preset').pack(side='left')
        self.prompt_choice=tk.StringVar()
        self.preset_combo=ttk.Combobox(row,textvariable=self.prompt_choice,state='readonly',width=33)
        self.preset_combo.pack(side='left',padx=8)
        self.button(row,'prompt_load',self.load_preset).pack(side='left')
        self.button(row,'save',self.save).pack(side='right')
        self.label(p,'prompt_hint',wraplength=980).pack(anchor='w',pady=10)
        self.label(p,'prompt_editor').pack(anchor='w')
        self.prompt_editor=scrolledtext.ScrolledText(p,height=10,wrap='word',font=('Segoe UI',11))
        self.prompt_editor.insert('1.0',self.settings.system_prompt or preset_text(self.settings.prompt_preset,self.settings.answer_language))
        self.prompt_editor.pack(fill='both',expand=True,pady=(5,8))
        self.check(p,'injection_guard','injection_guard').pack(anchor='w',pady=4)
        self.check(p,'include_comments','include_comments').pack(anchor='w',pady=4)
        self.label(p,'prompt_core').pack(anchor='w',pady=(8,3))
        self.core_preview=scrolledtext.ScrolledText(p,height=7,wrap='word',font=('Segoe UI',9))
        self.core_preview.pack(fill='both',expand=True)
        self.update_core_text()

    def update_core_text(self):
        if hasattr(self,'core_preview'):
            self.set_text(self.core_preview,CORE[self.vars['answer_language'].get()])

    def load_preset(self):
        index=self.preset_combo.current()
        key=list(PRESETS)[index if index>=0 else 0]
        self.vars['prompt_preset'].set(key)
        self.prompt_editor.delete('1.0','end')
        self.prompt_editor.insert('1.0',preset_text(key,self.vars['answer_language'].get()))
        self.vars['injection_guard'].set(PRESETS[key]['guard'])
        self.vars['include_comments'].set(not PRESETS[key]['exclude_comments'])
        self.update_core_text()

    def build_settings(self):
        p=self.scroll_panel(self.pages['settings_tab']);p.columnconfigure(1,weight=1)
        row=0
        self.label(p,'provider_preset').grid(row=row,column=0,sticky='w',padx=(0,16),pady=7)
        provider=ttk.Frame(p);provider.grid(row=row,column=1,sticky='ew')
        self.provider_choice=tk.StringVar(value='custom')
        ttk.Combobox(provider,textvariable=self.provider_choice,values=['custom','OpenAI','DeepSeek','local'],state='readonly',width=20).pack(side='left')
        self.button(provider,'provider_apply',self.apply_provider).pack(side='left',padx=8);row+=1
        for field,key in [('base_url','base_url'),('model','model'),('key','api_key')]:
            self.label(p,key).grid(row=row,column=0,sticky='w',padx=(0,16),pady=7)
            w=ttk.Entry(p,textvariable=self.vars[field],show='•' if field=='key' else '',width=55)
            w.grid(row=row,column=1,sticky='ew',pady=7);self.field_widgets[field]=w;row+=1
        for key in ('require_api_key','remember_key','vision','function_tools','asr'):
            self.check(p,key,key).grid(row=row,column=0,columnspan=2,sticky='w',pady=6);row+=1
        for key,values in [('answer_language',['cn','en']),('instruction_role',['system','developer']),
                           ('token_limit_parameter',['max_tokens','max_completion_tokens','omit'])]:
            self.label(p,key).grid(row=row,column=0,sticky='w',pady=7)
            combo=ttk.Combobox(p,textvariable=self.vars[key],values=values,state='readonly',width=25)
            combo.grid(row=row,column=1,sticky='w');row+=1
            if key=='answer_language':combo.bind('<<ComboboxSelected>>',lambda _:self.update_core_text())
        for key,lo,hi in [('initial_frames',0,8),('extra_frames',0,8),('max_minutes',1,120),
                          ('max_download_mb',16,1024),('max_output_tokens',64,64000),('api_timeout_seconds',10,600)]:
            self.label(p,key).grid(row=row,column=0,sticky='w',pady=6)
            ttk.Spinbox(p,from_=lo,to=hi,textvariable=self.vars[key],width=10).grid(row=row,column=1,sticky='w');row+=1
        self.label(p,'request_extra_json').grid(row=row,column=0,columnspan=2,sticky='w',pady=6);row+=1
        self.extra_editor=scrolledtext.ScrolledText(p,height=4,wrap='word',font=('Consolas',10))
        self.extra_editor.insert('1.0',self.settings.request_extra_json)
        self.extra_editor.grid(row=row,column=0,columnspan=2,sticky='ew');row+=1
        actions=ttk.Frame(p);actions.grid(row=row,column=0,columnspan=2,sticky='ew',pady=12)
        self.button(actions,'save',self.save).pack(side='left')
        self.button(actions,'test_api',self.test_api).pack(side='left',padx=8);row+=1
        self.label(p,'settings_hint',wraplength=960).grid(row=row,column=0,columnspan=2,sticky='w',pady=(0,10))

    def apply_provider(self):
        mode=self.provider_choice.get()
        presets={'OpenAI':('https://api.openai.com/v1','',True),
                 'DeepSeek':('https://api.deepseek.com','deepseek-flash',True),
                 'local':('http://127.0.0.1:11434/v1','',False)}
        if mode not in presets:return
        base,model,required=presets[mode]
        if self.vars['base_url'].get().rstrip('/')!=base:
            self.vars['key'].set('');self.vars['remember_key'].set(False)
        self.vars['base_url'].set(base);self.vars['model'].set(model)
        self.vars['require_api_key'].set(required)
        self.extra_editor.delete('1.0','end');self.extra_editor.insert('1.0','{}')
        if mode=='DeepSeek':
            self.extra_editor.delete('1.0','end')
            self.extra_editor.insert('1.0','{"thinking":{"type":"disabled"}}')
        self.status.set(self.t('provider_changed'))

    def build_diagnostics(self):
        p=self.pages['diagnostics_tab']
        self.label(p,'runtime_hint',wraplength=980).pack(anchor='w',pady=(0,12))
        self.paths=scrolledtext.ScrolledText(p,height=20,wrap='word',font=('Consolas',10))
        self.paths.pack(fill='both',expand=True)
        row=ttk.Frame(p);row.pack(fill='x',pady=12)
        self.button(row,'refresh',self.refresh_paths).pack(side='left')
        self.button(row,'save_diagnostics',self.diagnostics).pack(side='left',padx=8)
        self.refresh_paths()

    def set_text(self,w,text):
        w.configure(state='normal');w.delete('1.0','end');w.insert('1.0',text);w.configure(state='disabled')

    def refresh_paths(self):
        self.set_text(self.paths,json.dumps(path_report(),ensure_ascii=False,indent=2))

    def diagnostics(self):
        p=inside(RUNTIME/'exports'/'paths.json');atomic_json(p,path_report())
        messagebox.showinfo(self.t('info'),self.t('exported').format(path=p),parent=self.root)

    def change_language(self,_=None):
        default_question=self.question.get('1.0','end').strip() in (tr('default_question','cn'),tr('default_question','en'))
        self.lang=self.vars['language'].get().lower()
        if default_question:
            self.question.delete('1.0','end');self.question.insert('1.0',self.t('default_question'))
        self.settings.language=self.lang
        try:self.settings.save()
        except Exception as e:self.error(e)
        self.translate()

    def translate(self):
        self.root.title(self.t('app_title'))
        for w,key in self.text_bindings:w.configure(text=self.t(key))
        for k,page in self.pages.items():self.tabs.tab(page,text=self.t(k))
        for col,key in [('actual','time'),('requested','requested'),('source','source')]:self.frames.heading(col,text=self.t(key))
        for col,key in [('name','author'),('uid','uid'),('message','content')]:self.comment_tree.heading(col,text=self.t(key))
        self.update_targets()
        self.preset_combo.configure(values=[PRESETS[k]['name'][0 if self.lang=='cn' else 1] for k in PRESETS])
        self.preset_combo.current(list(PRESETS).index(self.vars['prompt_preset'].get()))
        self.auto_results.heading('video',text=self.t('target'))
        self.auto_results.heading('result',text=self.t('auto_result'))
        self.update_core_text()
        if not self.future:self.status.set(self.t('ready'))

    def update_targets(self):
        self.reply_label.set(self.t('reply_to')+': '+self.reply['name']+' · '+self.reply['rpid'] if self.reply else self.t('new_comment_mode'))
        self.mention_label.set(self.t('mentions')+': '+(' · '.join('@'+m.name+' (UID '+m.uid+')' for m in self.mentions) or self.t('none')))

    def read_settings(self):
        v=self.vars
        values={}
        integer_fields={'initial_frames','extra_frames','max_minutes','max_download_mb','max_output_tokens','api_timeout_seconds'}
        for name in vars(self.settings):
            if name=='language':values[name]=self.lang
            elif name=='system_prompt':values[name]=self.prompt_editor.get('1.0','end').strip()
            elif name=='request_extra_json':values[name]=self.extra_editor.get('1.0','end').strip() or '{}'
            else:values[name]=int(v[name].get()) if name in integer_fields else v[name].get()
        values['base_url']=values['base_url'].strip();values['model']=values['model'].strip()
        return Settings(**values).validate()

    def read_auto_plan(self):
        values={}
        integers={'interval_minutes','duration_minutes','max_videos','max_posts','daily_post_limit',
                  'daily_analysis_limit','owner_every_minutes','owner_daily_limit','quality_threshold',
                  'max_analyze_failures','analysis_backoff_minutes'}
        for name in vars(self.auto_plan):
            if name=='queue_text':values[name]=self.auto_queue.get('1.0','end').strip()
            elif name in integers:values[name]=int(self.auto_vars[name].get())
            elif isinstance(getattr(self.auto_plan,name),bool):values[name]=bool(self.auto_vars[name].get())
            else:values[name]=self.auto_vars[name].get()
        values['owner_uid']=values['owner_uid'].strip();values['start_time']=values['start_time'].strip()
        return AutoPlan(**values).validate()

    def save_auto(self):
        try:
            plan=self.read_auto_plan();plan.save();self.auto_plan=plan
            self.status.set(self.t('auto_saved'))
        except Exception as e:self.error(e)

    def toggle_auto(self):
        if not self.auto_enabled.get():
            if self.auto_running:self.cancel()
            return
        if self.future:
            self.auto_enabled.set(False)
            messagebox.showinfo(self.t('info'),self.t('busy'),parent=self.root);return
        try:
            plan=self.read_auto_plan();settings=self.read_settings()
            if plan.publish_comments and not self._auto_publish_confirmed(plan):
                self.auto_enabled.set(False);return
            plan.save();self.auto_plan=plan
            self.reply=None;self.mentions.clear();self.update_targets()
            self.auto_running=True
            self.task(self.service.run_auto(plan,settings,self.vars['key'].get().strip()),self.auto_done)
        except Exception as e:
            self.auto_running=False;self.auto_enabled.set(False);self.error(e)

    def _auto_publish_confirmed(self,plan):
        # Publication is irreversible, so it is confirmed once per switch-on.
        if plan.run_until_stopped:
            scope=self.t('auto_confirm_scope_always').format(analysis=plan.daily_analysis_limit,
                posts=plan.daily_post_limit,owner=plan.owner_daily_limit if plan.mention_owner else 0)
        else:
            scope=self.t('auto_confirm_scope_session').format(videos=plan.max_videos,
                posts=plan.max_posts,owner=plan.owner_daily_limit if plan.mention_owner else 0)
        body=self.t('auto_confirm_body').format(publish=scope)+'\n\n'+self.t('auto_confirm_note')
        return messagebox.askyesno(self.t('auto_confirm_title'),body,parent=self.root)

    def auto_done(self,report):
        self.auto_running=False;self.auto_enabled.set(False)
        self.status.set(self.t('auto_ended')+tr('auto_state_'+report['status'],self.lang))

    def _auto_detail(self,record):
        """Status plus the facts the outcome table used to drop."""
        parts=[tr('auto_state_'+str(record.get('status','')),self.lang)]
        status=record.get('status','')
        if record.get('mention_only') and record.get('owner_mentioned'):
            parts=[self.t('auto_mention_only_label')]
        if record.get('owner_mentioned'):
            name=record.get('owner_name') or record.get('owner_uid') or ''
            mark=self.t('auto_mentioned') if record.get('mentions_confirmed') else self.t('auto_mention_unconfirmed')
            parts.append(mark.format(name=name))
        elif record.get('mention_skipped') and status!='mention_skipped':
            parts.append(self.t('auto_mention_skipped_'+str(record['mention_skipped']))
                         if self.t('auto_mention_skipped_'+str(record['mention_skipped']))!='auto_mention_skipped_'+str(record['mention_skipped'])
                         else self.t('auto_mention_skipped').format(reason=tr('auto_state_'+str(record['mention_skipped']),self.lang)))
        if isinstance(record.get('score'),int):parts.append(self.t('auto_score').format(score=record['score']))
        if record.get('error'):parts.append(str(record['error']))
        return ' · '.join(x for x in parts if x)

    def save(self):
        try:
            settings=self.read_settings()
            save_key(self.vars['key'].get().strip(),settings.remember_key)
            settings.save();self.settings=settings
            remember_secret(self.vars['key'].get().strip())
            self.status.set(self.t('saved'))
        except Exception as e:self.error(e)

    def task(self,awaitable,on_done):
        if self.future:
            awaitable.close()
            messagebox.showinfo(self.t('info'),self.t('busy'),parent=self.root);return
        self.future=self.service.submit(awaitable)
        self.status.set(self.t('analyzing'))
        self.future.add_done_callback(lambda f:self.queue.put(('done',f,on_done)))

    def poll(self):
        try:
            while True:
                item=self.queue.get_nowait()
                if item[0]=='progress':
                    self.status.set(self.t(item[1])+str(item[2]))
                elif item[0]=='auto_video':
                    self.analysis_done(item[1])
                elif item[0]=='auto_update':
                    record=item[1]
                    self.auto_results.insert('','end',values=(record['video'],self._auto_detail(record)))
                    if len(self.auto_results.get_children())>200:self.auto_results.delete(self.auto_results.get_children()[0])
                elif item[0]=='done':
                    _,future,callback=item;self.future=None
                    if self.closing:continue
                    try:
                        value=future.result();callback(value)
                    except Exception as e:
                        self.auto_running=False;self.auto_enabled.set(False);self.error(e)
        except queue.Empty:pass
        if not self.closing:self.root.after(100,self.poll)

    def error(self,error):
        code=getattr(error,'code',str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__)
        detail=getattr(error,'detail','')
        # Never render raw HTTP bodies, credentials, cookies or signed media URLs.
        text=self.t(code)
        if text==code:
            text=('请检查设置及项目内日志。' if self.lang=='cn' else 'Check settings and project-local logs.')+'\n'+redact(code)
        if detail:text+='\n'+redact(detail)[:300]
        log.error('Operation failed code=%s',redact(code))
        self.status.set(self.t('error')+' · '+code)
        messagebox.showerror(self.t('error'),text,parent=self.root)

    def login_done(self,_):
        self.status.set(self.t('login_message'))

    def analyze(self):
        try:
            settings=self.read_settings();key=self.vars['key'].get().strip();remember_secret(key)
            question=self.question.get('1.0','end').strip() or self.t('default_question')
            if self.future:return
            # Clear reply/mention state when changing videos to avoid misdirected writes.
            self.reply=None;self.mentions.clear();self.update_targets()
            self.task(self.service.analyze(self.vars['target'].get(),question,settings,key),self.analysis_done)
        except Exception as e:self.error(e)

    def analysis_done(self,ev):
        self.display_evidence=ev
        self.video_title.set(ev.title+' · P'+str(ev.part)+' · '+timestamp(ev.scope_end)+' / '+timestamp(ev.duration))
        text=ev.answer
        if ev.notes:text+='\n\n'+self.t('notes')+'\n'+'\n'.join('• '+x for x in ev.notes)
        self.set_text(self.result,text)
        self.frames.delete(*self.frames.get_children())
        for i,f in enumerate(ev.frames):self.frames.insert('','end',iid=str(i),values=(timestamp(f['actual_s']),timestamp(f['requested_s']),f['source']))
        self.fill_comments(ev.comments)
        self.status.set(self.t('complete'))

    def show_frame(self,_=None):
        selection=self.frames.selection()
        ev=self.display_evidence
        if not selection or not ev:return
        try:
            f=ev.frames[int(selection[0])]
            image=tk.PhotoImage(file=str(inside(ROOT/f['path'])))
            scale=max(1,math.ceil(image.width()/1000),math.ceil(image.height()/700))
            if scale>1:image=image.subsample(scale,scale)
            window=tk.Toplevel(self.root);window.title(timestamp(f['actual_s']))
            w=ttk.Label(window,image=image);w.image=image;w.pack()
        except Exception as e:self.error(e)

    def export(self):
        if self.future:return
        try:
            p=self.service.export()
            messagebox.showinfo(self.t('info'),self.t('exported').format(path=p),parent=self.root)
        except Exception as e:self.error(e)

    def fill_comments(self,comments):
        self.comment_tree.delete(*self.comment_tree.get_children())
        for i,c in enumerate(comments):self.comment_tree.insert('','end',iid=str(i),values=(c['name'],c['uid'],c['message'].replace('\n',' ')[:200]))

    def fetch_comments(self):self.task(self.service.comments(),self.fill_comments)

    def select_reply(self):
        if self.future:return
        if self.display_evidence is not self.service.evidence:
            self.error(AppError('LOAD_FIRST'));return
        selection=self.comment_tree.selection()
        if not selection:
            messagebox.showinfo(self.t('info'),self.t('no_selection'),parent=self.root);return
        self.reply=self.service.evidence.comments[int(selection[0])].copy();self.update_targets()

    def clear_reply(self):
        self.reply=None;self.update_targets()

    def clear_mentions(self):
        self.mentions.clear();self.update_targets()

    def add_mention(self):
        def done(m):
            if len(self.mentions)>=5 or any(x.uid==m.uid or x.name==m.name for x in self.mentions):
                raise AppError('MENTION_AMBIGUOUS')
            self.mentions.append(m);self.uid.set('');self.update_targets()
        self.task(self.service.browser.lookup_user(self.uid.get().strip()),done)

    def draft(self):
        try:
            settings=self.read_settings()
            self.task(self.service.draft(self.t('draft_instruction'),settings,self.vars['key'].get()),self.draft_done)
        except Exception as e:self.error(e)

    def draft_done(self,text):
        self.compose.delete('1.0','end');self.compose.insert('1.0',text)
        self.status.set(self.t('ready'))

    def test_api(self):
        try:self.task(self.service.api_test(self.read_settings(),self.vars['key'].get()),lambda _:self.status.set(self.t('api_ok')))
        except Exception as e:self.error(e)

    def publish(self):
        if self.future:return
        try:
            ev=self.service.evidence
            if not ev or ev is not self.display_evidence:raise AppError('LOAD_FIRST')
            text=self.compose.get('1.0','end').strip()
            mentions=list(self.mentions)
            root=int(self.reply['root']) if self.reply else 0
            parent=int(self.reply['rpid']) if self.reply else 0
            preview=comment_payload(ev.aid,text,mentions,'preview',root,parent)['message']
            target=(self.reply['name']+' · '+str(parent)) if self.reply else self.t('new_comment_mode')
            notice=ev.title+'\n'+ev.url+'\n'+target+'\n'+self.mention_label.get()+'\n\n'+preview+'\n\n'+self.t('preview_footer')
            if messagebox.askyesno(self.t('preview_title'),notice,parent=self.root):
                self.task(self.service.publish(text,mentions,root,parent),self.published)
        except Exception as e:self.error(e)

    def published(self,value):
        text=self.t('posted').format(rpid=value['rpid'])
        if not value['mentions_confirmed']:text+='\n'+self.t('mention_unverified')
        messagebox.showinfo(self.t('info'),text,parent=self.root)
        self.status.set(text)

    def cancel(self):
        if self.future:
            self.service.stop.set();self.auto_enabled.set(False);self.status.set(self.t('cancel_pending'))

    def close(self):
        if self.closing:return
        self.closing=True;self.status.set(self.t('closing'))
        if self.future:self.future.cancel()
        f=self.service.shutdown()
        def wait(n=0):
            if f.done() or n>=200:
                self.root.destroy()
            else:self.root.after(100,lambda:wait(n+1))
        wait()

    def run(self):self.root.mainloop()
