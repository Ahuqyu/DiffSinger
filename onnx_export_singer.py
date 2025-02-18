# coding=utf8

import json
import os
import sys
import inference.svs.ds_e2e as e2e
from modules.fastspeech.pe import PitchExtractor
from usr.diff.shallow_diffusion_tts import GaussianDiffusion
from utils import load_ckpt
from utils.audio import save_wav
from utils.hparams import set_hparams, hparams

import acoustic.dfs_models as adm

import torch
import numpy as np

from utils.text_encoder import TokenTextEncoder
from usr.diffsinger_task import DIFF_DECODERS

root_dir = os.path.dirname(os.path.abspath(__file__))
os.environ['PYTHONPATH'] = f'"{root_dir}"'

sys.argv = [
    f'{root_dir}/inference/svs/ds_e2e.py',
    '--config',
    f'{root_dir}/usr/configs/midi/e2e/opencpop/ds100_adj_rel.yaml',
    '--exp_name',
    '0228_opencpop_ds100_rel'
]


class GaussianDiffusionWrap(adm.GaussianDiffusionFS):
    def forward(self, txt_tokens,
                # Wrapped Arguments
                spk_id,
                pitch_midi,
                midi_dur,
                is_slur,
                mel2ph,
                ):

        # print(f"txt_tokens: {txt_tokens}")
        # print(f"spk_id: {spk_id}")
        # print(f"pitch_midi: {pitch_midi}")
        # print(f"midi_dur: {midi_dur}")
        # print(f"is_slur: {is_slur}")
        # print(f"mel2ph: {mel2ph}")

        if (torch.numel(mel2ph) == 0):
            mel2ph = None
        if (torch.numel(txt_tokens) == 0):
            txt_tokens = None
        if (torch.numel(spk_id) == 0):
            spk_id = None
        if (torch.numel(pitch_midi) == 0):
            pitch_midi = None
        if (torch.numel(midi_dur) == 0):
            midi_dur = None
        if (torch.numel(is_slur) == 0):
            is_slur = None

        return super().forward(txt_tokens, spk_id=spk_id, ref_mels=None, infer=True,
                               pitch_midi=pitch_midi, midi_dur=midi_dur,
                               is_slur=is_slur, mel2ph=mel2ph)


class DFSInferWrapped(e2e.DiffSingerE2EInfer):
    def build_model(self):
        model = GaussianDiffusionWrap(
            phone_encoder=self.ph_encoder,
            out_dims=hparams['audio_num_mel_bins'], denoise_fn=DIFF_DECODERS[hparams['diff_decoder_type']](
                hparams),
            timesteps=hparams['timesteps'],
            K_step=hparams['K_step'],
            loss_type=hparams['diff_loss_type'],
            spec_min=hparams['spec_min'], spec_max=hparams['spec_max'],
        )

        model.eval()
        load_ckpt(model, hparams['work_dir'], 'model')

        if hparams.get('pe_enable') is not None and hparams['pe_enable']:
            self.pe = PitchExtractor().to(self.device)
            load_ckpt(self.pe, hparams['pe_ckpt'], 'model', strict=True)
            self.pe.eval()

        return model


class DFSInferWrapped2(e2e.DiffSingerE2EInfer):
    def build_model(self):
        model = adm.GaussianDiffusionDenoise(
            phone_encoder=self.ph_encoder,
            out_dims=hparams['audio_num_mel_bins'], denoise_fn=DIFF_DECODERS[hparams['diff_decoder_type']](
                hparams),
            timesteps=hparams['timesteps'],
            K_step=hparams['K_step'],
            loss_type=hparams['diff_loss_type'],
            spec_min=hparams['spec_min'], spec_max=hparams['spec_max'],
        )

        model.eval()
        load_ckpt(model, hparams['work_dir'], 'model')

        if hparams.get('pe_enable') is not None and hparams['pe_enable']:
            self.pe = PitchExtractor().to(self.device)
            load_ckpt(self.pe, hparams['pe_ckpt'], 'model', strict=True)
            self.pe.eval()

        return model


if __name__ == '__main__':

    set_hparams(print_hparams=False)

    dev = 'cuda'

    infer_ins = DFSInferWrapped(hparams)
    infer_ins.model.to(dev)

    infer_ins2 = DFSInferWrapped2(hparams)
    infer_ins2.model.to(dev)

    adm.device = dev

    inp = {
        'text': '小酒窝长睫毛AP是你最美的记号',
        'notes': 'C#4/Db4 | F#4/Gb4 | G#4/Ab4 | A#4/Bb4 F#4/Gb4 | F#4/Gb4 C#4/Db4 | C#4/Db4 | rest | C#4/Db4 | A#4/Bb4 | G#4/Ab4 | A#4/Bb4 | G#4/Ab4 | F4 | C#4/Db4',
        'notes_duration': '0.407140 | 0.376190 | 0.242180 | 0.509550 0.183420 | 0.315400 0.235020 | 0.361660 | 0.223070 | 0.377270 | 0.340550 | 0.299620 | 0.344510 | 0.283770 | 0.323390 | 0.360340',
        'input_type': 'word'
    }  # user input: Chinese characters

    with torch.no_grad():
        inp = infer_ins.preprocess_input(
            inp, input_type=inp['input_type'] if inp.get('input_type') else 'word')
        sample = infer_ins.input_to_batch(inp)
        txt_tokens = sample['txt_tokens']  # [B, T_t]
        spk_id = sample.get('spk_ids')

        pitch_midi = sample['pitch_midi']
        midi_dur = sample['midi_dur']
        is_slur = sample['is_slur']

        print(f'txt_tokens: {txt_tokens.shape}')
        print(f'pitch_midi: {pitch_midi.shape}')
        print(f'midi_dur: {midi_dur.shape}')
        print(f'is_slur: {is_slur.shape}')

        torch.onnx.export(
            infer_ins.model,
            (
                txt_tokens.to(dev),
                spk_id.to(dev),
                pitch_midi.to(dev),
                midi_dur.to(dev),
                is_slur.to(dev),
                spk_id.to(dev),
            ),
            "singer_fs.onnx",
            verbose=True,
            input_names=["txt_tokens", "spk_id",
                         "pitch_midi", "midi_dur", "is_slur", "mel2ph"],
            dynamic_axes={
                "txt_tokens": {
                    0: "a",
                    1: "b",
                },
                "spk_id": {
                    0: "a",
                    1: "b",
                },
                "pitch_midi": {
                    0: "a",
                    1: "b",
                },
                "midi_dur": {
                    0: "a",
                    1: "b",
                },
                "is_slur": {
                    0: "a",
                    1: "b",
                }
            },
            opset_version=11
        )

    inp = {
        "text": "AP 还 记 得 那 场 音 乐 会 的 烟 火  AP 还 记 得 那 个 凉 凉 的 深  秋  AP 还 记 得 人 潮 把 你 推 向 了 我  AP 游 乐 园 拥 挤 的 正 是 时 候  AP 一 个 夜 晚 坚 持 不 睡 的 等 候  AP 一 起 泡 温 泉 奢 侈 的 享  受  AP 有 一 次 日 记 里 愚 蠢 的 困 惑  AP 因 为 你 的 微 笑 幻 化 成 风  AP 你 大 大 的 勇 敢 保 护 着 我  AP 我 小 小 的 关 怀 喋 喋 不 休  AP 感 谢 我 们 一 起 走 了 那 么 久  AP 又 再 一 次 回 到  凉 凉 深 秋  AP 给 你 我 的 手 SP 像 温 柔 野 兽 AP 把 自 由 交 给 草 原 的 辽  阔   AP 我 们 小 手 拉 大 手 AP 一 起 郊  游 SP 今 天 别 想 太 多  AP 你 是 我 的 梦 AP 像 北 方 的 风 AP 吹 着 南 方 暖 洋 洋 的 哀  愁   AP 我 们 小 手 拉 大 手 AP 今 天 加  油 SP 向 昨 天 挥 挥  手   SP",
        "ph_seq": "AP h ai j i d e n a ch ang y in y ve h ui d e y an h uo uo AP h ai j i d e n a g e l iang l iang d e sh en en q iu iu AP h ai j i d e r en ch ao b a n i t ui x iang l e w o o AP y ou l e y van y ong j i d e zh eng sh i sh i h ou ou AP y i g e y e w an j ian ch i b u sh ui d e d eng h ou ou AP y i q i p ao w en q van sh e ch i d e x iang iang sh ou ou AP y ou y i c i r i j i l i y v ch un d e k un h uo uo AP y in w ei n i d e w ei x iao h uan h ua ch eng f eng eng AP n i d a d a d e y ong g an b ao h u zh e w o o AP w o x iao x iao d e g uan h uai d ie d ie b u x iu iu AP g an x ie w o m en y i q i z ou l e n a m e j iu iu AP y ou z ai y i c i h ui d ao ao l iang l iang sh en q iu iu AP g ei n i w o d e sh ou SP x iang w en r ou y e sh ou AP b a z i y ou j iao g ei c ao y van d e l iao iao k uo uo uo AP w o m en x iao sh ou l a d a sh ou AP y i q i j iao iao y ou SP j in t ian b ie x iang t ai d uo uo AP n i sh i w o d e m eng AP x iang b ei f ang d e f eng AP ch ui zh e n an f ang n uan y ang y ang d e ai ai ch ou ou ou AP w o m en x iao sh ou l a d a sh ou AP j in t ian j ia ia y ou SP x iang z uo t ian h ui h ui ui sh ou ou ou SP",
        "note_seq": "rest G3 G3 G3 G3 A3 A3 C4 C4 D4 D4 E4 E4 A4 A4 G4 G4 E4 E4 D4 D4 D4 D4 C4 rest C4 C4 D4 D4 C4 C4 B3 B3 C4 C4 F4 F4 A3 A3 C4 C4 D4 D4 E4 E4 E4 D4 rest D4 D4 E4 E4 D4 D4 C#4 C#4 D4 D4 G4 G4 B3 B3 D4 D4 E4 E4 D4 D4 D4 D4 C4 rest C4 C4 D4 D4 C4 C4 B3 B3 C4 C4 F4 F4 A3 A3 C4 C4 A3 A3 A3 A3 G3 rest G3 G3 G3 G3 A3 A3 C4 C4 D4 D4 E4 E4 A4 A4 G4 G4 E4 E4 D4 D4 D4 D4 C4 rest C4 C4 D4 D4 C4 C4 B3 B3 C4 C4 F4 F4 A3 A3 C4 C4 D4 D4 E4 E4 E4 D4 rest D4 D4 E4 E4 D4 D4 C#4 C#4 D4 D4 G4 G4 B3 B3 D4 D4 E4 E4 D4 D4 D4 D4 C4 rest C4 C4 D4 D4 C4 C4 B3 B3 C4 C4 F4 F4 A3 A3 C4 C4 D4 D4 D4 D4 C4 rest E4 E4 F4 F4 E4 E4 D4 D4 E4 E4 F4 F4 E4 E4 D4 D4 E4 E4 E4 E4 F4 rest F4 F4 G4 G4 F4 F4 G4 G4 F4 F4 E4 E4 D4 D4 C4 C4 D4 D4 D4 D4 E4 rest E4 E4 E4 E4 D4 D4 C#4 C#4 E4 E4 E4 E4 D4 D4 D4 D4 D4 D4 C#4 C#4 C#4 C#4 D4 rest D4 D4 D4 D4 E4 E4 F#4 F#4 D4 D4 G4 G4 A4 G4 G4 G4 G4 F#4 F#4 F#4 F#4 G4 rest E4 E4 F4 F4 E4 E4 F4 F4 G4 G4 rest E4 E4 F4 F4 E4 E4 F4 F4 G4 G4 rest G4 G4 A4 A4 G4 G4 A4 A4 B4 B4 C5 C5 E4 E4 E4 E4 G4 G4 A4 A4 A4 G4 G4 rest C4 C4 D4 D4 C4 C4 F4 F4 E4 E4 D4 D4 C4 C4 rest F4 F4 E4 E4 D4 D4 C4 C4 C4 rest C4 C4 D4 D4 A3 A3 C4 C4 E4 E4 E4 E4 G4 rest E4 E4 F4 F4 E4 E4 F4 F4 G4 G4 rest E4 E4 F4 F4 E4 E4 F4 F4 G4 G4 rest G4 G4 A4 A4 G4 G4 A4 A4 B4 B4 C5 C5 E4 E4 E4 E4 G4 A4 A4 A4 G4 G4 rest C4 C4 D4 D4 C4 C4 F4 F4 E4 E4 D4 D4 C4 C4 rest F4 F4 E4 E4 D4 D4 C4 C4 C4 rest C4 C4 D4 D4 A3 A3 C4 C4 C4 C4 D4 D4 D4 C4 C4 rest",
        "note_dur_seq": "0.6 0.29218 0.29218 0.289358 0.289358 0.200769 0.200769 0.21282 0.21282 0.278718 0.278718 0.461538 0.461538 0.169423 0.169423 0.522884 0.522884 0.230769 0.230769 0.200768 0.200768 0.30577 0.30577 0.302885 0.314423 0.182052 0.182052 0.309486 0.309486 0.212052 0.212052 0.234487 0.234487 0.230768 0.230768 0.461666 0.461666 0.245642 0.245642 0.335193 0.335193 0.301154 0.301154 0.188012 0.374488 0.374488 0.288462 0.343847 0.191731 0.191731 0.284806 0.284806 0.230769 0.230769 0.1925 0.1925 0.269038 0.269038 0.416538 0.416538 0.232179 0.232179 0.40013 0.40013 0.305768 0.305768 0.252502 0.252502 0.284037 0.284037 0.274038 0.393268 0.212823 0.212823 0.228717 0.228717 0.230769 0.230769 0.195062 0.195062 0.266092 0.266092 0.401922 0.401922 0.224103 0.224103 0.423205 0.423205 0.506541 0.506541 0.335769 0.335769 0.274038 0.373269 0.147946 0.147946 0.313592 0.313592 0.230769 0.230769 0.230771 0.230771 0.153521 0.153521 0.523783 0.523783 0.171155 0.171155 0.536154 0.536154 0.217755 0.217755 0.213784 0.213784 0.305768 0.305768 0.288462 0.358846 0.156602 0.156602 0.274937 0.274937 0.237691 0.237691 0.223847 0.223847 0.206023 0.206023 0.411284 0.411284 0.335769 0.335769 0.362692 0.362692 0.259232 0.259232 0.196152 0.42404 0.42404 0.230769 0.373271 0.169932 0.169932 0.224616 0.224616 0.297759 0.297759 0.200766 0.200766 0.202178 0.202178 0.520132 0.520132 0.172561 0.172561 0.519747 0.519747 0.174544 0.174544 0.246543 0.246543 0.316218 0.316218 0.274038 0.393268 0.201862 0.201862 0.224677 0.224677 0.245772 0.245772 0.230765 0.230765 0.159743 0.159743 0.472567 0.472567 0.255062 0.255062 0.381793 0.381793 0.450713 0.450713 0.430895 0.430895 0.317308 0.300961 0.201923 0.201923 0.277567 0.277567 0.225059 0.225059 0.202567 0.202567 0.212821 0.212821 0.495642 0.495642 0.177497 0.177497 0.454805 0.454805 0.490774 0.490774 0.219999 0.219999 0.418269 0.317951 0.146472 0.146472 0.281734 0.281734 0.261725 0.261725 0.215774 0.215774 0.18737 0.18737 0.519933 0.519933 0.184619 0.184619 0.47769 0.47769 0.387759 0.387759 0.307435 0.307435 0.389423 0.314999 0.176089 0.176089 0.300448 0.300448 0.20077 0.20077 0.260772 0.260772 0.132239 0.132239 0.488848 0.488848 0.299037 0.299037 0.40449 0.40449 0.260768 0.260768 0.229999 0.229999 0.234425 0.234425 0.461538 0.257883 0.173526 0.173526 0.30519 0.30519 0.12564 0.12564 0.288726 0.288726 0.243713 0.243713 0.191862 0.191862 0.271729 0.224616 0.224616 0.390127 0.390127 0.446539 0.446539 0.296796 0.296796 0.346154 0.372691 0.245772 0.245772 0.230765 0.230765 0.230773 0.230773 0.154036 0.154036 0.669808 0.669808 0.240002 0.320765 0.320765 0.230773 0.230773 0.230765 0.230765 0.154235 0.154235 0.669613 0.669613 0.330002 0.161406 0.161406 0.300128 0.300128 0.215579 0.215579 0.245963 0.245963 0.156989 0.156989 0.535318 0.535318 0.230765 0.230765 0.43154 0.43154 0.190386 0.190386 0.245194 0.374998 0.374998 0.418269 0.375 0.281472 0.206603 0.206603 0.213011 0.213011 0.187179 0.187179 0.507887 0.507887 0.202178 0.202178 0.416666 0.416666 0.523464 0.523464 0.272302 0.14603 0.14603 0.486288 0.486288 0.379034 0.379034 0.10878 0.309489 0.309489 0.140773 0.219737 0.219737 0.517568 0.517568 0.159747 0.159747 0.442556 0.442556 0.520964 0.520964 0.219808 0.219808 0.432692 0.301156 0.156398 0.156398 0.305141 0.305141 0.230769 0.230769 0.164477 0.164477 0.702636 0.702636 0.196736 0.320766 0.320766 0.200763 0.200763 0.260776 0.260776 0.164668 0.164668 0.702445 0.702445 0.226735 0.249805 0.249805 0.241725 0.241725 0.23077 0.23077 0.245777 0.245777 0.211666 0.211666 0.495642 0.495642 0.230769 0.230769 0.446531 0.446531 0.189813 0.211423 0.40877 0.40877 0.403846 0.302885 0.344417 0.21577 0.21577 0.192134 0.192134 0.217311 0.217311 0.513632 0.513632 0.206942 0.206942 0.407118 0.407118 0.527675 0.527675 0.197889 0.260768 0.260768 0.43334 0.43334 0.377233 0.377233 0.142502 0.218075 0.218075 0.153459 0.259494 0.259494 0.44782 0.44782 0.241672 0.241672 0.401343 0.401343 0.299097 0.299097 0.173413 0.374664 0.374664 0.475962 0.389423 0.5",
        "is_slur_seq": "0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 1 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 1 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 1 1 0",
        "ph_dur": "0.6 0.165 0.12718 0.103589 0.185769 0.045 0.155769 0.075 0.13782 0.092949 0.185769 0.045 0.416538 0.045 0.124423 0.106346 0.416538 0.045 0.185769 0.045 0.155768 0.075001 0.230769 0.302885 0.314423 0.075 0.107052 0.123717 0.185769 0.045 0.167052 0.063717 0.17077 0.059999 0.170769 0.06 0.401666 0.059873 0.185769 0.045 0.290193 0.171346 0.129808 0.188012 0.143719 0.230769 0.288462 0.343847 0.059999 0.131732 0.099037 0.185769 0.045 0.185769 0.045 0.1475 0.083269 0.185769 0.045 0.371538 0.09 0.142179 0.088591 0.311539 0.15 0.155768 0.075001 0.177501 0.053268 0.230769 0.274038 0.393268 0.025002 0.187821 0.042948 0.185769 0.045 0.185769 0.045 0.150062 0.080708 0.185384 0.045385 0.356537 0.105001 0.119102 0.111668 0.311537 0.150002 0.356539 0.105 0.230769 0.274038 0.373269 0.045 0.102946 0.127823 0.185769 0.045 0.185769 0.045 0.185771 0.044998 0.108523 0.122246 0.401537 0.060001 0.111154 0.119616 0.416538 0.045 0.172755 0.058014 0.15577 0.074999 0.230769 0.288462 0.358846 0.045 0.111602 0.119167 0.15577 0.074999 0.162692 0.068077 0.15577 0.074999 0.131024 0.099745 0.311539 0.15 0.185769 0.045 0.317692 0.143847 0.115385 0.196152 0.150002 0.274038 0.230769 0.373271 0.044998 0.124934 0.105835 0.118781 0.111988 0.185771 0.044998 0.155768 0.075001 0.127177 0.103592 0.41654 0.044998 0.127563 0.103207 0.41654 0.044998 0.129546 0.101223 0.14532 0.085449 0.230769 0.274038 0.393268 0.025002 0.17686 0.053909 0.170768 0.060001 0.185771 0.044998 0.185767 0.045002 0.114741 0.116028 0.356539 0.105 0.150062 0.080708 0.301085 0.160454 0.290259 0.17128 0.259615 0.317308 0.300961 0.045193 0.15673 0.074039 0.203528 0.027241 0.197818 0.032951 0.169616 0.061153 0.151668 0.079102 0.41654 0.044998 0.132499 0.09827 0.356535 0.105003 0.385771 0.075768 0.144231 0.418269 0.317951 0.042625 0.103847 0.126923 0.154811 0.075958 0.185767 0.045002 0.170772 0.059998 0.127372 0.103397 0.416536 0.045002 0.139617 0.091152 0.386538 0.075001 0.312758 0.148781 0.158654 0.389423 0.314999 0.060001 0.116088 0.114681 0.185767 0.045002 0.155768 0.075001 0.185771 0.044998 0.087241 0.143528 0.34532 0.116219 0.182818 0.047951 0.356539 0.105 0.155768 0.075001 0.154998 0.075771 0.158654 0.461538 0.257883 0.045002 0.128524 0.102245 0.202945 0.027824 0.097816 0.132954 0.155772 0.074997 0.168716 0.062054 0.129808 0.271729 0.060001 0.164615 0.066154 0.323973 0.137566 0.308973 0.152565 0.144231 0.346154 0.372691 0.060001 0.185771 0.044998 0.185767 0.045002 0.185771 0.044998 0.109038 0.121731 0.548077 0.240002 0.134998 0.185767 0.045002 0.185771 0.044998 0.185767 0.045002 0.109233 0.121536 0.548077 0.330002 0.044998 0.116408 0.114361 0.185767 0.045002 0.170577 0.060192 0.185771 0.044998 0.111991 0.118778 0.41654 0.044998 0.185767 0.045002 0.386538 0.075001 0.115385 0.245194 0.10096 0.274038 0.418269 0.375 0.281472 0.035835 0.170768 0.060001 0.15301 0.077759 0.10942 0.121349 0.386538 0.075001 0.127177 0.103592 0.313074 0.148464 0.375 0.272302 0.045006 0.101024 0.129745 0.356543 0.104996 0.274038 0.10878 0.07872 0.230769 0.140773 0.089996 0.129741 0.101028 0.41654 0.044998 0.114749 0.11602 0.326536 0.135002 0.385962 0.075577 0.144231 0.432692 0.301156 0.044998 0.1114 0.11937 0.185771 0.044998 0.185771 0.044998 0.119479 0.11129 0.591346 0.196736 0.134995 0.185771 0.044998 0.155765 0.075005 0.185771 0.044998 0.11967 0.111099 0.591346 0.226735 0.104996 0.144809 0.08596 0.155765 0.075005 0.155765 0.075005 0.170772 0.059998 0.151668 0.079102 0.41654 0.044998 0.185771 0.044998 0.401533 0.189813 0.211423 0.120308 0.288462 0.403846 0.302885 0.344417 0.045006 0.170764 0.060005 0.132129 0.09864 0.118671 0.112099 0.401533 0.060005 0.146937 0.083832 0.323286 0.138252 0.389423 0.197889 0.104996 0.155772 0.074997 0.358343 0.103195 0.274038 0.142502 0.044998 0.173077 0.153459 0.135002 0.124492 0.106277 0.341543 0.119995 0.121677 0.109093 0.29225 0.169289 0.129808 0.173413 0.158318 0.216346 0.475962 0.389423 0.5",
        "input_type": "phoneme"
    }

    with torch.no_grad():
        inp = infer_ins.preprocess_input(
            inp, input_type=inp['input_type'] if inp.get('input_type') else 'word')
        sample = infer_ins.input_to_batch(inp)
        txt_tokens = sample['txt_tokens']  # [B, T_t]
        spk_id = sample.get('spk_ids')

        pitch_midi = sample['pitch_midi']
        midi_dur = sample['midi_dur']
        is_slur = sample['is_slur']
        mel2ph = sample['mel2ph']

        print(f'txt_tokens: {txt_tokens.shape}')
        print(f'pitch_midi: {pitch_midi.shape}')
        print(f'midi_dur: {midi_dur.shape}')
        print(f'is_slur: {is_slur.shape}')
        print(f'mel2ph: {mel2ph.shape}')


        torch.onnx.export(
            infer_ins.model,
            (
                txt_tokens.to(dev),
                spk_id.to(dev),
                pitch_midi.to(dev),
                midi_dur.to(dev),
                is_slur.to(dev),
                mel2ph.to(dev),
            ),
            "singer_fs_ph.onnx",
            verbose=True,
            input_names=["txt_tokens", "spk_id",
                         "pitch_midi", "midi_dur", "is_slur", "mel2ph"],
            dynamic_axes={
                "txt_tokens": {
                    0: "a",
                    1: "b",
                },
                "spk_id": {
                    0: "a",
                    1: "b",
                },
                "pitch_midi": {
                    0: "a",
                    1: "b",
                },
                "midi_dur": {
                    0: "a",
                    1: "b",
                },
                "is_slur": {
                    0: "a",
                    1: "b",
                },
                "mel2ph": {
                    0: "a",
                    1: "b",
                }
            },
            opset_version=11
        )

    with torch.no_grad():
        torch.onnx.export(
            infer_ins2.model,
            (
                torch.rand(1, 1, 80, 967).to(dev),
                torch.full((1,), 1, dtype=torch.long).to(dev),
                torch.rand(1, 256, 967).to(dev),
            ),
            "singer_denoise.onnx",
            verbose=True,
            input_names=[
                "x",
                "t",
                "cond",
            ],
            dynamic_axes={
                "x": {
                    0: "batch_size",
                    2: "num_mel_bin",
                    3: "frames",
                },
                "cond": {
                    0: "batch_size",
                    1: "what",
                    2: "frames",
                },
            },
            opset_version=11
        )

    print("OK")
