import mne
import pandas as pd # For better display of annotations if there are many

filepath = "path/to/study-recording_EventsUpdated.set"
try:
    # When loading .set files, MNE automatically tries to create annotations
    # from the EEG.event structure.
    raw = mne.io.read_raw_eeglab(filepath, preload=True, verbose='WARNING') # verbose='INFO' or True might give more load details
    print("Channel names:", raw.ch_names)
    print("-" * 30)

    if raw.annotations:
        print(f"Found {len(raw.annotations)} MNE Annotation(s):")
        # For a cleaner display if many annotations:
        # Convert to DataFrame (optional, but nice for viewing)
        # annotations_df = raw.annotations.to_data_frame()
        # print(annotations_df.head()) # Print first few

        # Or iterate and print:
        for i, annot in enumerate(raw.annotations):
            print(f"  Annotation {i+1}:")
            print(f"    Onset (s):      {annot['onset']:.3f}")
            print(f"    Duration (s):   {annot['duration']:.3f}")
            print(f"    Description:    '{annot['description']}'") # THIS IS KEY!
            # MNE might also store original EEGLAB event fields if available
            if 'orig_time' in annot: # MNE < 1.6
                print(f"    Original Time:  {annot['orig_time']}")
            if 'type' in annot.get('orig_event', {}): # MNE >= 1.6 stores original EEGLAB event here
                print(f"    Original EEGLAB type: '{annot['orig_event']['type']}'")


        # If you see your event markers here, you would use mne.events_from_annotations()
        # Example of how you might then create an event_id dictionary based on descriptions:
        # Assume your descriptions are strings like '1', '2', '101', 'stim_A', etc.
        # And your GUI event_id_map is like {'Condition Label 1': 1, 'Condition Label 2': 2}

        # This is just an example to show the concept, your actual mapping will depend
        # on what's in raw.annotations.description and your GUI's event_id_map.

        # print("\nAttempting to create events from annotations (example mapping):")
        # # Create a mapping from the unique descriptions found in raw.annotations
        # # to the integer IDs your GUI expects for those conditions.
        # # This part requires knowing how your GUI's label-to-ID map corresponds
        # # to the 'description' strings in raw.annotations.
        #
        # # Example: If raw.annotations.description contains strings '1', '2', etc.
        # # and your GUI self.validated_params['event_id_map'] is {'Fruit vs Veg': 1, 'Veg vs Fruit': 2}
        # # you want to map the *description* '1' to the *label* 'Fruit vs Veg' for mne.events_from_annotations

        # Example mapping if descriptions are strings of numbers:
        # event_id_for_mne = {desc: val for desc, val in app.validated_params['event_id_map'].items() if str(val) in raw.annotations.description}
        # This is tricky because mne.events_from_annotations wants a map from description string to integer event_id.
        # Your current GUI map is label string -> integer event_id.

        # Let's first confirm what the descriptions ARE.
        # The key is that `mne.events_from_annotations` will use the `description` field
        # of the annotation. You need to build an `event_id` dictionary for it that looks like:
        # `{'description_string_1': mapped_id_1, 'description_string_2': mapped_id_2}`
        # where `mapped_id_1` is what you use in your `mne.Epochs` call later.

    else:
        print("No MNE Annotations found in the raw data.")

except FileNotFoundError:
    print(f"Error: File not found at {filepath}")
except Exception as e:
    print(f"An error occurred: {e}")
    print(traceback.format_exc())
