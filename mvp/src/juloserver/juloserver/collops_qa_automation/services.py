from juloserver.collops_qa_automation.constant import QAAirudderResponse, QAAirudderAPIPhase
from juloserver.collops_qa_automation.models import AirudderRecordingUpload, RecordingReport


def construct_task_for_airudder(
        qa_airudder_client, task_name, data_to_send_recording_details,
        airudder_upload_id
):
    task_id, response_status, response_code = qa_airudder_client.create_task(
        task_name=task_name
    )
    record_airudder_upload_history(
        None, QAAirudderAPIPhase.CREATING_TASK,
        airudder_upload_id=airudder_upload_id,
        task_id=task_id, airudder_response_status=response_status,
        airudder_response_code=response_code
    )
    upload_response_status, upload_response_code = qa_airudder_client.upload_recording_file_to_airudder(
        task_id, data_to_send_recording_details
    )

    record_airudder_upload_history(
        None, QAAirudderAPIPhase.UPLOAD_RECORDING,
        task_id=task_id,
        airudder_upload_id=airudder_upload_id,
        airudder_response_status=upload_response_status,
        airudder_response_code=upload_response_code
    )
    if upload_response_status != QAAirudderResponse.OK:
        return ''

    return task_id


def record_airudder_upload_history(
        vendor_recording_detail_id, phase, airudder_response_code=None,
        airudder_response_status=None,
        task_id=None, airudder_upload_id=None
):
    if phase == QAAirudderAPIPhase.INITIATED:
        airudder_recording = AirudderRecordingUpload.objects.create(
            phase=phase, vendor_recording_detail_id=vendor_recording_detail_id
        )
        return airudder_recording.id

    if airudder_upload_id:
        airudder_recording = AirudderRecordingUpload.objects.filter(
            id=airudder_upload_id
        ).last()
    else:
        airudder_recording = AirudderRecordingUpload.objects.filter(
            vendor_recording_detail_id=vendor_recording_detail_id
        ).last()

    if not airudder_recording:
        return

    airudder_recording.update_safely(
        phase=phase, task_id=task_id,
        status=airudder_response_status, code=airudder_response_code
    )


def process_timeline_sentences(data):
    sentence = ''
    for item in data:
        begin_time = item.get('Begin')
        processed_sentence = "{}'{}: {} \n ".format(
            begin_time[:2], begin_time[2:], item.get('Sentence')
        )
        sentence += processed_sentence

    return sentence


def store_airudder_recording_report_callback(task_id, qa_details):
    airudder_recording_upload = AirudderRecordingUpload.objects.filter(
        task_id=task_id
    ).last()
    if not airudder_recording_upload:
        return []

    recording_report_ids = []
    for data in qa_details:
        l_channel_sentence = [item for item in data['AsrResults'] if item['Channel'] == '1']
        r_channel_sentence = [item for item in data['AsrResults'] if item['Channel'] == '2']
        negative_checkpoint_data = next(
            (item for item in data['CheckPoint'] if item['CheckPointType'] == 'Negative'), None)
        l_channel_checkpoint_negative_result = [
            item for item in negative_checkpoint_data['CheckPointResultsDetail']
            if item['Channel'] == '1']
        r_channel_checkpoint_negative_result = [
            item for item in negative_checkpoint_data['CheckPointResultsDetail']
            if item['Channel'] == '2']
        sop_checkpoint_data = next(
            (item for item in data['CheckPoint'] if item['CheckPointType'] == 'SOP'), None)
        l_channel_sop_checkpoint_result = [item for item in sop_checkpoint_data['CheckPointResultsDetail']
                                           if item['Channel'] == '1']
        r_channel_sop_checkpoint_result = [item for item in sop_checkpoint_data['CheckPointResultsDetail']
                                           if item['Channel'] == '2']
        l_channel_sop_scores = next(
            (item for item in data['Scores'] if item['CheckPointType'] == 'SOP' and
             item['Channel'] == '1'), None)
        r_channel_sop_scores = next(
            (item for item in data['Scores'] if item['CheckPointType'] == 'SOP' and
             item['Channel'] == '2'), None)
        l_channel_negative_score = next(
            (item for item in data['Scores'] if item['CheckPointType'] == 'Negative' and
             item['Channel'] == '1'), None)
        r_channel_negative_score = next(
            (item for item in data['Scores'] if item['CheckPointType'] == 'Negative' and
             item['Channel'] == '2'), None)
        l_channel_negative_score_value = '' if not l_channel_negative_score else \
            l_channel_negative_score.get('Score', '')
        l_channel_sop_score_value = '' if not l_channel_sop_scores else \
            l_channel_sop_scores.get('Score', '')
        r_channel_negative_score_value = '' if not r_channel_negative_score else \
            r_channel_negative_score.get('Score', '')
        r_channel_sop_score_value = '' if not r_channel_sop_scores else \
            r_channel_sop_scores.get('Score', '')
        recording_report = RecordingReport.objects.create(
            airudder_recording_upload=airudder_recording_upload,
            length=int(data.get('Length', 0)),
            total_words=int(data.get('Words', 0)),
            l_channel_sentence=process_timeline_sentences(l_channel_sentence),
            l_channel_negative_checkpoint=process_timeline_sentences(
                l_channel_checkpoint_negative_result
            ),
            l_channel_negative_score=l_channel_negative_score_value,
            l_channel_sop_checkpoint=process_timeline_sentences(
                l_channel_sop_checkpoint_result),
            l_channel_sop_score=l_channel_sop_score_value,
            r_channel_sentence=process_timeline_sentences(r_channel_sentence),
            r_channel_negative_checkpoint=process_timeline_sentences(
                r_channel_checkpoint_negative_result
            ),
            r_channel_negative_score=r_channel_negative_score_value,
            r_channel_sop_checkpoint=process_timeline_sentences(
                r_channel_sop_checkpoint_result),
            r_channel_sop_score=r_channel_sop_score_value,
        )
        recording_report_ids.append(recording_report.id)

    return recording_report_ids
