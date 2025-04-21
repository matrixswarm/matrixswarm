
class PermanentIdExtract(object):
    @staticmethod
    def get_dict_by_permanent_id(data, permanent_id):
        for item in data:
            if item.get("permanent_id") == permanent_id:  # Match on permanent_id
                return item  # Return the whole dictionary

        return {}  # If no match is found


